import json

from ..tls import TLS_SERVER_NAME
from .base import Adapter, service


class Hysteria2(Adapter):
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
            "listen": f":{context.control}",
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
                    "listen": f"127.0.0.1:{context.internal(index)}",
                    "remote": f'{port["host"]}:{port["target"]}',
                }
            )
            entry["listeners"].append(context.internal(index))
            entry["backends"].append((port, "127.0.0.1", context.internal(index), context.link))
        # JSON is accepted by Hysteria's configuration loader and avoids YAML quoting ambiguities.
        for plan, role, config in ((entry, "client", client), (exit, "server", server)):
            plan["files"][name + ".json"] = json.dumps(config, indent=2)
            plan["units"][context.tag + ".service"] = service(
                f"/var/lib/tunnel-manager/{context.namespace}/bin/hysteria {role} -c {context.root}/{name}.json"
            )
        exit["udp_listeners"].append(context.control)
        exit["firewall"].append(
            {
                "protocol": "udp",
                "source": context.entry["address"],
                "port": context.control,
            }
        )
