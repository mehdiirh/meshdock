"""Compile broad GRE mappings to bounded Linux rules instead of per-port listeners."""

from ipaddress import IPv4Address

from .ports import segments


def span(first, last):
    return str(first) if first == last else f"{first}:{last}"


def configure_ranges(context, entry, exit, interface, local_ip, peer_ip):
    for plan, source in ((entry, peer_ip), (exit, local_ip)):
        plan["firewall"].append({"protocol": "icmp", "source": source, "interface": interface})
        plan["gre_checks"].append({"interface": interface, "peer": source})
        plan["network_interfaces"].append(interface)
    entry["forwarding_addresses"].append(context.entry["address"])
    if any(IPv4Address(mapping["host"]).is_loopback for mapping in context.link["ports"]):
        exit["loopback_interfaces"].append(interface)
    for mapping in context.link["ports"]:
        for start, end, target, target_end in segments(mapping):
            public_ports, target_ports = span(start, end), span(target, target_end)
            destination = peer_ip
            if start != target:
                destination += f":{target}" if start == end else f":{target}-{target_end}/{start}"
                if start != end:
                    entry["shifted_ranges"] = True
            entry["forwarded_ranges"].append(
                {"address": context.entry["address"], "protocol": "tcp", "start": start, "end": end}
            )
            entry["network_rules"]["pre"].append(
                f'-d {context.entry["address"]} -p tcp --dport {public_ports} -j DNAT --to-destination {destination}'
            )
            entry["network_rules"]["post"].append(
                f"-o {interface} -d {peer_ip} -p tcp --dport {target_ports} -j SNAT --to-source {local_ip}"
            )
            entry["network_rules"]["forward"].append(
                f"-o {interface} -d {peer_ip} -p tcp --dport {target_ports} -j ACCEPT"
            )
            exit["network_rules"]["pre"].append(
                f'-i {interface} -s {local_ip} -d {peer_ip} -p tcp --dport {target_ports} -j DNAT --to-destination {mapping["host"]}'
            )
            exit["firewall"].append(
                {
                    "protocol": "tcp",
                    "source": local_ip,
                    "interface": interface,
                    "destination": mapping["host"],
                    "port": target_ports,
                }
            )
            if not IPv4Address(mapping["host"]).is_loopback:
                exit["network_rules"]["forward"].append(
                    f'-i {interface} -s {local_ip} -d {mapping["host"]} -p tcp --dport {target_ports} -j ACCEPT'
                )
                exit["network_rules"]["post"].append(
                    f'-s {local_ip} -d {mapping["host"]} -p tcp --dport {target_ports} -j MASQUERADE'
                )
    entry["network_rules"]["forward"].append(
        f"-i {interface} -s {peer_ip} -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT"
    )
    exit["network_rules"]["forward"].append(
        f"-o {interface} -d {local_ip} -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT"
    )
    for plan in (entry, exit):
        for direction in ("-i", "-o"):
            plan["network_rules"]["mss"].append(
                f"{direction} {interface} -p tcp --tcp-flags SYN,RST SYN -j TCPMSS --clamp-mss-to-pmtu"
            )
