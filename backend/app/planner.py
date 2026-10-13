"""Pure desired-state compiler. Plans contain secrets: never log or expose them."""

from collections import defaultdict

from .methods import REGISTRY
from .methods.base import Context, service
from .security import unseal


def empty():
    return {
        "files": {},
        "units": {},
        "interfaces": [],
        "firewall": [],
        "binaries": [],
        "backends": [],
        "relay": [],
        "checks": [],
        "listeners": [],
        "udp_listeners": [],
        "method_count": 0,
    }


def build(snapshot):
    servers = {s["id"]: s for s in snapshot["servers"]}
    plans = {id: empty() for id in servers}
    namespace = snapshot["namespace"]
    for link in snapshot["links"]:
        if not link["enabled"]:
            continue
        entry_plan, exit_plan = plans[link["entry_id"]], plans[link["exit_id"]]
        REGISTRY[link["method"]].configure(
            Context(
                namespace,
                link,
                servers[link["entry_id"]],
                servers[link["exit_id"]],
                unseal(link["encrypted"]),
            ),
            entry_plan,
            exit_plan,
        )
        entry_plan["method_count"] += 1
        exit_plan["method_count"] += 1
        # Destination checks run on the exit, including loopback services such as an existing proxy.
        for plan in link["ports"]:
            exit_plan["checks"].append({"host": plan["host"], "port": plan["target"]})
    for plan in plans.values():
        pool = defaultdict(list)
        for mapping, host, port, link in plan.pop("backends"):
            pool[mapping["public"]].append((host, port, link))
        config = f"""global
  maxconn 65536
  stats socket /run/tm-{namespace}-stats.sock mode 600 level admin
  hard-stop-after 30s
defaults
  mode tcp
  timeout connect 10s
  timeout client 1h
  timeout server 1h
  timeout check 5s
  option tcpka
"""
        for public, backends in sorted(pool.items()):
            policy = backends[0][2]["policy"]
            config += f'listen public_{public}\n  bind 0.0.0.0:{public}\n  balance {"roundrobin" if policy=="failover" else policy}\n'
            for i, (host, port, link) in enumerate(
                sorted(backends, key=lambda x: x[2]["slot"])
            ):
                config += (
                    f'  server edge_{link["slot"]} {host}:{port} weight {link["weight"]} check inter 3s fall 3 rise 2'
                    + (" backup" if policy == "failover" and i else "")
                    + "\n"
                )
                plan["checks"].append({"host": host, "port": port})
            plan["listeners"].append(public)
            plan["firewall"].append(
                {"protocol": "tcp", "source": "0.0.0.0/0", "port": public}
            )
        relays = plan.pop("relay")
        for r in relays:
            config += f'listen relay_{r["name"]}\n  bind {r["bind"]}:{r["port"]}\n  server target {r["host"]}:{r["target"]} check inter 3s\n'
            plan["listeners"].append(r["port"])
        if pool or relays:
            plan["files"]["haproxy.cfg"] = config
            plan["units"][f"tm-{namespace}-router.service"] = service(
                f"/usr/sbin/haproxy -Ws -f /var/lib/tunnel-manager/{namespace}/current/haproxy.cfg -p /run/tm-{namespace}-haproxy.pid",
                extra="ExecReload=/bin/kill -USR2 $MAINPID\nKillMode=mixed",
                kind="notify",
            )
        if plan["firewall"]:
            from .firewall import script

            plan["files"]["firewall.sh"] = script(namespace, plan["firewall"])
            plan["units"][f"tm-{namespace}-firewall.service"] = service(
                f"/bin/sh /var/lib/tunnel-manager/{namespace}/current/firewall.sh",
                extra="RemainAfterExit=yes",
                kind="oneshot",
            )
        plan["binaries"] = sorted(set(plan["binaries"]))
        plan["listeners"] = sorted(set(plan["listeners"]))
    return plans
