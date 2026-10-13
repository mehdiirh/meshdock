import json

from .base import Adapter, service
from .options import Options, option, toml_values


class RatholeOptions(Options):
    nodelay: bool = option(True)
    keepalive_secs: int = option(20, ge=1, le=3600, unit="seconds")
    keepalive_interval: int = option(8, ge=1, le=300, unit="seconds")
    heartbeat_interval: int = option(30, ge=1, le=300, unit="seconds", scope="server")
    heartbeat_timeout: int = option(40, ge=2, le=3600, unit="seconds", scope="client")
    retry_interval: int = option(1, ge=1, le=300, unit="seconds", scope="client")
    rules = [{"left": "heartbeat_interval", "operator": "lt", "right": "heartbeat_timeout"}]


class Rathole(Adapter):
    options_model = RatholeOptions
    metadata = {
        "id": "rathole",
        "name": "Rathole",
        "encrypted": True,
        "direction": "exit-to-entry",
        "protocols": ["tcp"],
        "requirements": ["outbound-tcp"],
    }

    def configure(self, context, entry, exit):
        options = self.options(context.link)
        server = f"""[server]
heartbeat_interval = {options.heartbeat_interval}
bind_addr = "{context.entry['address']}:{context.control}"
[server.transport]
type = "noise"
[server.transport.noise]
local_private_key = {json.dumps(context.secrets['noise_private'])}
"""
        client = f"""[client]
heartbeat_timeout = {options.heartbeat_timeout}
retry_interval = {options.retry_interval}
remote_addr = "{context.entry['address']}:{context.control}"
[client.transport]
type = "noise"
[client.transport.noise]
remote_public_key = {json.dumps(context.secrets['noise_public'])}
"""
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
            server += f'[server.services.{name}]\ntoken = {token}\nbind_addr = "{context.bind_address}:{context.internal(index)}"\n'
            client += f'[client.services.{name}]\ntoken = {token}\nlocal_addr = "{port["host"]}:{port["target"]}"\n'
            entry["backends"].append(
                (port, context.bind_address, context.internal(index), context.link)
            )
            entry["listeners"].append(context.internal(index))
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
