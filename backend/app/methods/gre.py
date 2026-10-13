from ipaddress import IPv4Address

from ..gre_forwarding import configure_ranges
from ..ports import bounds, segments
from ..security import AppError
from .base import Adapter, service


class GRE(Adapter):
    control_protocol = None
    native_ranges = True
    internal_on_exit = True

    def internal_address(self, link):
        return str(IPv4Address(int(IPv4Address("10.253.0.0")) + link["slot"] * 4 + 2))

    def kernel_mapping(self, link):
        return any(
            bounds(p["public"])[0] != bounds(p["public"])[1] or p.get("exclude")
            for p in link["ports"]
        )

    metadata = {
        "id": "gre",
        "name": "GRE",
        "encrypted": False,
        "direction": "entry-to-exit",
        "protocols": ["tcp"],
        "requirements": ["protocol-47", "public-ipv4"],
    }

    def validate_mappings(self, link):
        super().validate_mappings(link)
        if not self.kernel_mapping(link):
            return
        targets = []
        for mapping in link["ports"]:
            for _, _, first, last in segments(mapping):
                if any(
                    host != mapping["host"] and max(first, start) <= min(last, end)
                    for start, end, host in targets
                ):
                    raise AppError("range_target_conflict")
                targets.append((first, last, mapping["host"]))

    def bindings(self, context, entry, exit):
        ip_b = str(IPv4Address(int(IPv4Address("10.253.0.0")) + context.link["slot"] * 4 + 2))
        for port in context.link.get("internal_ports", []):
            exit["sockets"].append({"address": ip_b, "port": port, "protocol": "tcp"})

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
                extra=f"RemainAfterExit=yes\nExecStopPost=/bin/sh {context.root}/{name} down",
                kind="oneshot",
            )
            plan["interfaces"].append({"name": iface, "network": str(IPv4Address(first)) + "/30"})
            plan["firewall"].append({"protocol": "gre", "source": peer["address"]})
        if self.kernel_mapping(context.link):
            configure_ranges(context, entry, exit, iface, ip_a, ip_b)
            return
        for index, port in enumerate(context.link["ports"]):
            internal_port = context.internal(index)
            exit["relay"].append(
                {
                    "bind": ip_b,
                    "port": internal_port,
                    "host": port["host"],
                    "target": port["target"],
                    "name": f'g{context.link["slot"]}_{index}',
                }
            )
            exit["firewall"].append({"protocol": "tcp", "source": ip_a, "port": internal_port})
            entry["backends"].append((port, ip_b, internal_port, context.link))
