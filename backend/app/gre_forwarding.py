"""Compact HAProxy range forwarding over GRE, with no NAT or forwarding sysctls."""

from .ports import segments
from .security import AppError


def configure_ranges(context, entry, exit, interface, local_ip, peer_ip):
    for plan, source in ((entry, peer_ip), (exit, local_ip)):
        plan["firewall"].append({"protocol": "icmp", "source": source, "interface": interface})
        plan["gre_checks"].append({"interface": interface, "peer": source})

    intervals = [segment for mapping in context.link["ports"] for segment in segments(mapping)]
    for index, mapping in enumerate(context.link["ports"]):
        for part, (start, end, target, target_end) in enumerate(segments(mapping)):
            # A destination on our own relay would loop instead of reaching an app.
            if mapping["host"] == peer_ip and any(
                max(target, first) <= min(target_end, last) for first, last, _, _ in intervals
            ):
                raise AppError("range_target_conflict")
            name = f"gre_{context.link['slot']}_{index}_{part}"
            for plan, address, host, offset, source in (
                (entry, context.entry["address"], peer_ip, 0, local_ip),
                (exit, peer_ip, mapping["host"], target - start, None),
            ):
                plan["proxy_ranges"].append(
                    {
                        "name": name,
                        "address": address,
                        "start": start,
                        "end": end,
                        "host": host,
                        "offset": offset,
                        "source": source,
                    }
                )
                plan["socket_ranges"].append(
                    {"address": address, "protocol": "tcp", "start": start, "end": end}
                )
                rule = {
                    "protocol": "tcp",
                    "source": "0.0.0.0/0" if plan is entry else local_ip,
                    "destination": address,
                    "port": str(start) if start == end else f"{start}:{end}",
                }
                if plan is exit:
                    rule["interface"] = interface
                plan["firewall"].append(rule)
                plan["forward_count"] += end - start + 1


def range_config(proxy):
    """HAProxy's signed server port preserves offsets without per-port backends."""
    first, last = proxy["start"], proxy["end"]
    ports = str(first) if first == last else f"{first}-{last}"
    offset = f":{proxy['offset']:+d}" if proxy["offset"] else ""
    source = f"  source {proxy['source']}\n" if proxy["source"] else ""
    # Range destinations may intentionally be closed. Readiness checks the GRE
    # peer and every local listener instead of probing every application port.
    return (
        f"listen {proxy['name']}\n"
        f"  bind {proxy['address']}:{ports}\n"
        f"{source}"
        f"  server target {proxy['host']}{offset}\n"
    )
