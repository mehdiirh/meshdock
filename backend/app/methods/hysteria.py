import json

from ..tls import TLS_SERVER_NAME
from .base import Adapter, service
from .options import Options, option


class HysteriaOptions(Options):
    obfuscation: bool = option(True)
    stream_receive_window: int = option(8388608, ge=65536, le=268435456, unit="bytes")
    connection_receive_window: int = option(20971520, ge=65536, le=1073741824, unit="bytes")
    max_idle_timeout: int = option(30, ge=4, le=120, unit="seconds")
    keepalive_period: int = option(10, ge=1, le=60, unit="seconds", scope="client")
    disable_path_mtu_discovery: bool = option(False)
    rules = [
        {"left": "stream_receive_window", "operator": "lte", "right": "connection_receive_window"},
        {"left": "keepalive_period", "operator": "lt", "right": "max_idle_timeout"},
    ]


class Hysteria2(Adapter):
    options_model = HysteriaOptions
    control_protocol = "udp"

    metadata = {
        "id": "hysteria2",
        "name": "Hysteria 2",
        "encrypted": True,
        "direction": "entry-to-exit",
        "protocols": ["tcp"],
        "requirements": ["outbound-udp", "pinned-private-tls"],
        "priority": 2,
        "score": 3.55,
        "caveat": "udp_required",
    }

    def configure(self, context, entry, exit):
        options = self.options(context.link)
        name = context.filename
        for plan in (entry, exit):
            plan["files"][name + "-ca.crt"] = context.secrets["tls_cert"]
            plan["binaries"].append("hysteria")
        exit["files"][name + "-tls.key"] = context.secrets["tls_key"]
        obfuscation = {
            "type": "salamander",
            "salamander": {"password": context.secrets["token"]},
        }
        server = {
            "listen": f"{context.exit['address']}:{context.control}",
            "tls": {
                "cert": f"{context.root}/{name}-ca.crt",
                "key": f"{context.root}/{name}-tls.key",
            },
            "auth": {"type": "password", "password": context.secrets["token"]},
            "obfs": obfuscation,
            "disableUDP": True,
        }
        client = {
            "server": f'{context.exit["address"]}:{context.control}',
            "auth": context.secrets["token"],
            "tls": {"sni": TLS_SERVER_NAME, "ca": f"{context.root}/{name}-ca.crt"},
            "obfs": obfuscation,
            "tcpForwarding": [],
        }
        for index, port in enumerate(context.link["ports"]):
            client["tcpForwarding"].append(
                {
                    "listen": f"{context.bind_address}:{context.internal(index)}",
                    "remote": f'{port["host"]}:{port["target"]}',
                }
            )
            entry["listeners"].append(context.internal(index))
            entry["backends"].append(
                (port, context.bind_address, context.internal(index), context.link)
            )
        # JSON is accepted by Hysteria's configuration loader and avoids YAML quoting ambiguities.
        for plan, role, config in ((entry, "client", client), (exit, "server", server)):
            if not options.obfuscation:
                config.pop("obfs")
            config["quic"] = {
                "initStreamReceiveWindow": options.stream_receive_window,
                "maxStreamReceiveWindow": options.stream_receive_window,
                "initConnReceiveWindow": options.connection_receive_window,
                "maxConnReceiveWindow": options.connection_receive_window,
                "maxIdleTimeout": f"{options.max_idle_timeout}s",
                "disablePathMTUDiscovery": options.disable_path_mtu_discovery,
            }
            if role == "client":
                config["quic"]["keepAlivePeriod"] = f"{options.keepalive_period}s"
            plan["files"][name + ".json"] = json.dumps(config, indent=2)
            plan["units"][context.tag + ".service"] = service(
                f"/var/lib/meshdock/{context.namespace}/bin/hysteria {role} -c {context.root}/{name}.json"
            )
        exit["udp_listeners"].append(context.control)
        exit["firewall"].append(
            {
                "protocol": "udp",
                "source": context.entry["address"],
                "port": context.control,
                "destination": context.exit["address"],
            }
        )
