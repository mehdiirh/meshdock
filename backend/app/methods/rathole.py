import json
from typing import Literal

from .base import Adapter, service
from .options import Options, option, toml_values
from .tls_bridge import tls_server, verified_client


class RatholeOptions(Options):
    transport: Literal["tcp", "noise", "tls", "ws", "wss"] = option("noise")
    nodelay: bool = option(True)
    keepalive_secs: int = option(20, ge=1, le=3600, unit="seconds")
    keepalive_interval: int = option(8, ge=1, le=300, unit="seconds")
    heartbeat_interval: int = option(30, ge=1, le=300, unit="seconds", scope="server")
    heartbeat_timeout: int = option(40, ge=2, le=3600, unit="seconds", scope="client")
    retry_interval: int = option(1, ge=1, le=300, unit="seconds", scope="client")
    rules = [{"left": "heartbeat_interval", "operator": "lt", "right": "heartbeat_timeout"}]


class Rathole(Adapter):
    options_model = RatholeOptions
    transports = {
        name: {
            "encrypted": name in ("noise", "tls", "wss"),
            "control_protocols": ["tcp"],
            "tls_mode": "verified_bridge" if name in ("tls", "wss") else "none",
            "architectures": ["x86_64"] if name in ("ws", "wss") else ["x86_64", "aarch64"],
        }
        for name in RatholeOptions.model_fields["transport"].annotation.__args__
    }

    def auxiliary_counts(self, link):
        count = int(self.options(link).transport in ("tls", "wss"))
        return count, count

    metadata = {
        "id": "rathole",
        "name": "Rathole",
        "encrypted": True,
        "direction": "exit-to-entry",
        "protocols": ["tcp", "udp"],
        "requirements": ["outbound-tcp"],
    }

    def configure(self, context, entry, exit):
        options = self.options(context.link)
        if options.transport in ("ws", "wss"):
            for plan in (entry, exit):
                plan.setdefault("architecture_requirements", []).append(
                    {
                        "method": "rathole",
                        "transport": options.transport,
                        "supported": ["x86_64"],
                    }
                )
        server_address = f"{context.entry['address']}:{context.control}"
        remote_address = server_address
        if options.transport in ("tls", "wss"):
            server_address = tls_server(context, entry)
            remote_address = verified_client(context, exit)
        native_transport = {"tls": "tcp", "ws": "websocket", "wss": "websocket"}.get(
            options.transport, options.transport
        )
        server = f"""[server]
heartbeat_interval = {options.heartbeat_interval}
bind_addr = "{server_address}"
[server.transport]
type = "{native_transport}"
"""
        client = f"""[client]
heartbeat_timeout = {options.heartbeat_timeout}
retry_interval = {options.retry_interval}
remote_addr = "{remote_address}"
[client.transport]
type = "{native_transport}"
"""
        if options.transport == "noise":
            server += f'[server.transport.noise]\nlocal_private_key = {json.dumps(context.secrets["noise_private"])}\n'
            client += f'[client.transport.noise]\nremote_public_key = {json.dumps(context.secrets["noise_public"])}\n'
        if native_transport == "websocket":
            server += "[server.transport.websocket]\ntls = false\n"
            client += "[client.transport.websocket]\ntls = false\n"
        tcp = toml_values(
            {
                key: getattr(options, key)
                for key in ("nodelay", "keepalive_secs", "keepalive_interval")
            }
        )
        server += "[server.transport.tcp]\n" + tcp
        client += "[client.transport.tcp]\n" + tcp
        for index, port in enumerate(context.link["ports"]):
            name = f's{context.link["slot"]}_{index}'
            token = json.dumps(context.secrets["token"])
            server += f'[server.services.{name}]\ntype = {json.dumps(port.get("protocol", "tcp"))}\ntoken = {token}\nbind_addr = "{context.bind_address}:{context.internal(index)}"\n'
            client += f'[client.services.{name}]\ntype = {json.dumps(port.get("protocol", "tcp"))}\ntoken = {token}\nlocal_addr = "{port["host"]}:{port["target"]}"\n'
            entry["backends"].append(
                (port, context.bind_address, context.internal(index), context.link)
            )
            entry["udp_listeners" if port.get("protocol") == "udp" else "listeners"].append(
                context.internal(index)
            )
        entry["files"][context.filename + ".toml"] = server
        exit["files"][context.filename + ".toml"] = client
        for plan in (entry, exit):
            plan["binaries"].append("rathole")
            plan["units"][context.tag + ".service"] = service(
                f"/var/lib/meshdock/{context.namespace}/bin/rathole {context.root}/{context.filename}.toml"
            )
        entry["firewall"].append(
            {
                "protocol": "tcp",
                "source": context.exit["address"],
                "port": context.control,
                "destination": context.entry["address"],
            }
        )
        entry["listeners"].append(context.control)
