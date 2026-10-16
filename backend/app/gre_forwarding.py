"""Compact HAProxy range forwarding over GRE, with no NAT or forwarding sysctls."""

from .ports import segments, protocols
from .security import AppError


def relay_offset(link, unavailable):
    """Keep relay ports away from destinations that may listen on all addresses.

    A single offset preserves compact ranges and their exceptions. If a broad
    mapping cannot fit another contiguous span, retain the original ports and
    let actual listener preflight decide whether that binding is safe.
    """
    intervals = [
        segment
        for mapping in link["ports"]
        if "tcp" in protocols(mapping)
        for segment in segments(mapping)
    ]
    if not intervals or not any(
        port in unavailable for first, last, _, _ in intervals for port in range(first, last + 1)
    ):
        return 0
    first = min(segment[0] for segment in intervals)
    width = max(segment[1] for segment in intervals) - first + 1
    run = 0
    candidates = []
    for port in range(1, 65536):
        run = 0 if port in unavailable else run + 1
        if run >= width:
            candidates.append(port - width + 1)
    if not candidates:
        return 0
    start = next((port for port in candidates if port >= 30000), candidates[0])
    return start - first


def configure_ranges(context, entry, exit, interface, local_ip, peer_ip):
    for plan, source in ((entry, peer_ip), (exit, local_ip)):
        plan["firewall"].append({"protocol": "icmp", "source": source, "interface": interface})
        plan["gre_checks"].append({"interface": interface, "peer": source})

    shift = context.link.get("relay_port_offset", 0)
    intervals = [
        segment
        for mapping in context.link["ports"]
        if "tcp" in protocols(mapping)
        for segment in segments(mapping)
    ]
    for index, mapping in enumerate(context.link["ports"]):
        if "tcp" not in protocols(mapping):
            continue
        for part, (start, end, target, target_end) in enumerate(segments(mapping)):
            # A destination on our own relay would loop instead of reaching an app.
            if mapping["host"] == peer_ip and any(
                max(target, first + shift) <= min(target_end, last + shift)
                for first, last, _, _ in intervals
            ):
                raise AppError("range_target_conflict")
            name = f"gre_{context.link['slot']}_{index}_{part}"
            for plan, address, host, offset, source, bind_shift in (
                (entry, context.entry["address"], peer_ip, shift, local_ip, 0),
                (exit, peer_ip, mapping["host"], target - start - shift, None, shift),
            ):
                bind_start, bind_end = start + bind_shift, end + bind_shift
                plan["proxy_ranges"].append(
                    {
                        "name": name,
                        "address": address,
                        "start": bind_start,
                        "end": bind_end,
                        "host": host,
                        "offset": offset,
                        "source": source,
                    }
                )
                plan["socket_ranges"].append(
                    {"address": address, "protocol": "tcp", "start": bind_start, "end": bind_end}
                )
                rule = {
                    "protocol": "tcp",
                    "source": "0.0.0.0/0" if plan is entry else local_ip,
                    "destination": address,
                    "port": (
                        str(bind_start) if bind_start == bind_end else f"{bind_start}:{bind_end}"
                    ),
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
