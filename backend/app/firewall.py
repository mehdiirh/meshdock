"""Boot-time restoration of an installation's isolated INPUT accept chain."""


def script(namespace, rules):
    chain = "TM_" + namespace.upper()
    lines = [
        "#!/bin/sh",
        "set -eu",
        f"iptables -w -N {chain} 2>/dev/null || true",
        "iptables-restore -w --noflush <<'TM_RULES'",
        "*filter",
        f"-F {chain}",
    ]
    for rule in rules:
        line = f'-A {chain} -s {rule["source"]} -p {rule["protocol"]}'
        if rule.get("interface"):
            line += f' -i {rule["interface"]}'
        if rule.get("destination"):
            line += f' -d {rule["destination"]}'
        if rule["protocol"] in ("tcp", "udp"):
            line += f' --dport {rule["port"]}'
        lines.append(line + " -j ACCEPT")
    lines.extend(
        [
            "COMMIT",
            "TM_RULES",
            f"iptables -w -C INPUT -j {chain} 2>/dev/null || iptables -w -I INPUT 1 -j {chain}",
            "",
        ]
    )
    return "\n".join(lines)
