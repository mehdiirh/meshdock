"""Owned UDP packet forwarding; TCP continues to use HAProxy.

Socket transports listen on a per-link dummy address, so UDP frontends need no
shared Nginx, extra proxy daemon, or relaxation of public loopback filtering.
"""

from ipaddress import IPv4Address

from .methods.base import service
from .ports import protocols, segments


def span(first, last):
    return str(first) if first == last else f"{first}:{last}"


def translated(host, first, last, target):
    if first == target:
        return host
    if first == last:
        return f"{host}:{target}"
    return f"{host}:{target}-{target + last - first}/{first}"


def private_address(context, plan):
    interface = "mu" + context.namespace[:6] + str(context.link["slot"])
    script = context.filename + "-address.sh"
    plan["files"][script] = f"""#!/bin/sh
set -eu
case "$1" in
up)
 ip link add {interface} type dummy
 ip address add {context.bind_address}/32 dev {interface}
 ip link set {interface} up
 ;;
down) ip link del {interface} 2>/dev/null || true ;;
esac
"""
    unit = context.tag + "-address.service"
    for name in list(plan["units"]):
        if name.startswith(context.tag + ".") or name.startswith(context.tag + "-"):
            plan["units"][name] = plan["units"][name].replace(
                "After=network-online.target",
                f"After=network-online.target {unit}\nRequires={unit}",
            )
    plan["units"][unit] = service(
        f"/bin/sh {context.root}/{context.filename}-address.sh up",
        extra=f"RemainAfterExit=yes\nExecStopPost=/bin/sh {context.root}/{context.filename}-address.sh down",
        kind="oneshot",
    )
    plan["interfaces"].append({"name": interface, "network": context.bind_address + "/32"})
    return interface


def local_frontends(context, entry, exit):
    """Expose only selected UDP rows; native private listeners stay private."""
    if not any("udp" in protocols(p) for p in context.link["ports"]):
        return
    interface = private_address(context, entry)
    private_address(context, exit)
    entry["network_interfaces"].append(interface)
    rows = sorted(
        (p["public"], context.internal(i))
        for i, p in enumerate(context.link["ports"])
        if p.get("protocol") == "udp"
    )
    groups = []
    for public, internal in rows:
        if (
            groups
            and public == groups[-1][1] + 1
            and internal == groups[-1][2] + public - groups[-1][0]
        ):
            groups[-1][1] = public
        else:
            groups.append([public, public, internal])
    for first, last, target in groups:
        entry["forwarded_ranges"].append(
            {"address": context.entry["address"], "protocol": "udp", "start": first, "end": last}
        )
        entry["network_rules"]["pre"].append(
            f'-d {context.entry["address"]} -p udp --dport {span(first, last)} -j DNAT --to-destination {translated(context.bind_address, first, last, target)}'
        )
        entry["shifted_ranges"] |= first != target and first != last
        entry["firewall"].append(
            {
                "protocol": "udp",
                "source": "0.0.0.0/0",
                "destination": context.bind_address,
                "port": span(target, target + last - first),
                "original_destination": context.entry["address"],
            }
        )
    # Unsolicited traffic to the private relay address is never a public API.
    for plan in (entry, exit):
        for protocol in ("tcp", "udp"):
            plan["firewall"].append(
                {
                    "protocol": protocol,
                    "source": "0.0.0.0/0",
                    "destination": context.bind_address,
                    "action": "DROP",
                    "nonlocal": True,
                }
            )


def gre_ranges(context, entry, exit, interface, local_ip, peer_ip):
    mappings = [m for m in context.link["ports"] if "udp" in protocols(m)]
    if not mappings:
        return
    for plan, peer in ((entry, peer_ip), (exit, local_ip)):
        plan["network_interfaces"].append(interface)
        check = {"interface": interface, "peer": peer}
        if check not in plan["gre_checks"]:
            plan["gre_checks"].append(check)
            plan["firewall"].append({"protocol": "icmp", "source": peer, "interface": interface})
    entry["forwarding_addresses"].append(context.entry["address"])
    if any(IPv4Address(m["host"]).is_loopback for m in mappings):
        exit["loopback_interfaces"].append(interface)
    for mapping in mappings:
        for first, last, target, end in segments(mapping):
            public, destination = span(first, last), span(target, end)
            entry["forwarded_ranges"].append(
                {
                    "address": context.entry["address"],
                    "protocol": "udp",
                    "start": first,
                    "end": last,
                }
            )
            entry["network_rules"]["pre"].append(
                f'-d {context.entry["address"]} -p udp --dport {public} -j DNAT --to-destination {peer_ip}'
            )
            exit["shifted_ranges"] |= first != target and first != last
            entry["network_rules"]["post"].append(
                f"-o {interface} -d {peer_ip} -p udp --dport {public} -j SNAT --to-source {local_ip}"
            )
            entry["network_rules"]["forward"].append(
                f"-o {interface} -d {peer_ip} -p udp --dport {public} -j ACCEPT"
            )
            exit["network_rules"]["pre"].append(
                f'-i {interface} -s {local_ip} -d {peer_ip} -p udp --dport {public} -j DNAT --to-destination {translated(mapping["host"], first, last, target)}'
            )
            exit["firewall"].append(
                {
                    "protocol": "udp",
                    "source": local_ip,
                    "interface": interface,
                    "destination": mapping["host"],
                    "port": destination,
                }
            )
            if not IPv4Address(mapping["host"]).is_loopback:
                exit.setdefault("forwarding_targets", []).append(mapping["host"])
                exit["network_rules"]["forward"].append(
                    f'-i {interface} -s {local_ip} -d {mapping["host"]} -p udp --dport {destination} -j ACCEPT'
                )
                exit["network_rules"]["post"].append(
                    f'-s {local_ip} -d {mapping["host"]} -p udp --dport {destination} -j MASQUERADE'
                )
    entry["network_rules"]["forward"].append(
        f"-i {interface} -s {peer_ip} -p udp -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT"
    )
    exit["network_rules"]["forward"].append(
        f"-o {interface} -d {local_ip} -p udp -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT"
    )
