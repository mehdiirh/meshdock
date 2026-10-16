"""Boot-time restoration of an installation's isolated INPUT accept chain."""

from collections import defaultdict


def compact(rules):
    """Merge adjacent ports only when every other match has identical scope."""
    groups = defaultdict(set)
    guards = []
    for rule in rules:
        if rule.get("action") == "DROP":
            guards.append(rule)
            continue
        if rule["protocol"] not in ("tcp", "udp") or not isinstance(rule.get("port"), int):
            yield rule
            continue
        key = tuple(sorted((key, value) for key, value in rule.items() if key != "port"))
        groups[key].add(rule["port"])
    for key, ports in groups.items():
        ordered = sorted(ports)
        first = last = ordered[0]
        for port in ordered[1:]:
            if port == last + 1:
                last = port
                continue
            yield {**dict(key), "port": first if first == last else f"{first}:{last}"}
            first = last = port
        yield {**dict(key), "port": first if first == last else f"{first}:{last}"}

    yield from guards


def script(namespace, rules):
    chain = "MESHDOCK_" + namespace.upper()
    lines = [
        "#!/bin/sh",
        "set -eu",
        f"iptables -w -N {chain} 2>/dev/null || true",
        "iptables-restore -w --noflush <<'MESHDOCK_RULES'",
        "*filter",
        f"-F {chain}",
    ]
    for rule in compact(rules):
        line = f'-A {chain} -s {rule["source"]} -p {rule["protocol"]}'
        if rule.get("interface"):
            line += f' -i {rule["interface"]}'
        if rule.get("destination"):
            line += f' -d {rule["destination"]}'
        if rule["protocol"] in ("tcp", "udp") and "port" in rule:
            line += f' --dport {rule["port"]}'
        if rule.get("original_destination"):
            line += f' -m conntrack --ctstate DNAT --ctorigdst {rule["original_destination"]}'
        if rule.get("nonlocal"):
            line += " ! -i lo"
        lines.append(line + " -j " + rule.get("action", "ACCEPT"))
    lines.extend(
        [
            "COMMIT",
            "MESHDOCK_RULES",
            f"iptables -w -C INPUT -j {chain} 2>/dev/null || iptables -w -I INPUT 1 -j {chain}",
            "",
        ]
    )
    return "\n".join(lines)
