from ipaddress import IPv4Address

from .base import Adapter, service


class GRE(Adapter):
    metadata = {
        "id": "gre",
        "name": "GRE",
        "encrypted": False,
        "direction": "entry-to-exit",
        "protocols": ["tcp"],
        "requirements": ["protocol-47", "public-ipv4"],
    }

    def configure(self, context, entry, exit):
        first = int(IPv4Address("10.253.0.0")) + context.link["slot"] * 4
        ip_a, ip_b = str(IPv4Address(first + 1)), str(IPv4Address(first + 2))
        iface = "tm" + context.namespace[:6] + str(context.link["slot"])
        for plan, local, peer, ip in (
            (entry, context.entry, context.exit, ip_a),
            (exit, context.exit, context.entry, ip_b),
        ):
            name = context.filename + "-gre.sh"
            script = f"""#!/bin/sh
set -eu
case "$1" in
up)
 ip tunnel add {iface} mode gre local {local['address']} remote {peer['address']} key {context.link['slot']} ttl 64
 ip address add {ip}/30 dev {iface}
 ip link set {iface} mtu 1400 up
 ;;
down) ip tunnel del {iface} 2>/dev/null || true ;;
esac
"""
            plan["files"][name] = script
            plan["units"][context.tag + "-gre.service"] = service(
                f"/bin/sh {context.root}/{name} up",
                extra=f"RemainAfterExit=yes\nExecStop=/bin/sh {context.root}/{name} down",
                kind="oneshot",
            )
            plan["interfaces"].append(
                {"name": iface, "network": str(IPv4Address(first)) + "/30"}
            )
            plan["firewall"].append({"protocol": "gre", "source": peer["address"]})
        for index, port in enumerate(context.link["ports"]):
            port = context.internal(index)
            exit["relay"].append(
                {
                    "bind": ip_b,
                    "port": port,
                    "host": port["host"],
                    "target": port["target"],
                    "name": f'g{context.link["slot"]}_{index}',
                }
            )
            exit["firewall"].append({"protocol": "tcp", "source": ip_a, "port": port})
            entry["backends"].append((port, ip_b, port, context.link))
