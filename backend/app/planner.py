"""Pure desired-state compiler. Plans contain secrets: never log or expose them."""

from collections import defaultdict

from .allocation import allocate
from .methods import REGISTRY
from .methods.base import Context, service
from .security import AppError, unseal
from .tls import TLS_SERVER_NAME


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
        "sockets": [],
        "forwarded_ranges": [],
        "network_rules": {"pre": [], "post": [], "forward": [], "mss": []},
        "network_interfaces": [],
        "forwarding_addresses": [],
        "loopback_interfaces": [],
        "gre_checks": [],
        "shifted_ranges": False,
        "forward_count": 0,
    }


def build(snapshot):
    servers = {s["id"]: s for s in snapshot["servers"]}
    plans = {id: empty() for id in servers}
    namespace = snapshot["namespace"]
    for link in allocate(snapshot):
        if not link["enabled"]:
            continue
        entry_plan, exit_plan = plans[link["entry_id"]], plans[link["exit_id"]]
        adapter = REGISTRY[link["method"]]
        context = Context(
            namespace,
            link,
            servers[link["entry_id"]],
            servers[link["exit_id"]],
            unseal(link["encrypted"]),
        )
        adapter.configure(context, entry_plan, exit_plan)
        adapter.bindings(context, entry_plan, exit_plan)
        entry_plan["method_count"] += 1
        exit_plan["method_count"] += 1
        # Destination checks run on the exit, including loopback services such as an existing proxy.
        if not adapter.kernel_mapping(link):
            entry_plan["forward_count"] += len(link["ports"])
            exit_plan["forward_count"] += len(link["ports"])
        if not adapter.kernel_mapping(link) and not link.get("range_mapping"):
            for mapping in link["ports"]:
                exit_plan["checks"].append({"host": mapping["host"], "port": mapping["target"]})
    for server_id, plan in plans.items():
        public_address = servers[server_id]["address"]
        if plan["method_count"]:
            plan["public_address"] = public_address
        pool = defaultdict(list)
        for mapping, host, port, link in plan.pop("backends"):
            pool[mapping["public"]].append((host, port, link, mapping.get("health_group", 0)))
        config = f"""global
  maxconn 65536
  stats socket /run/meshdock-{namespace}-stats.sock mode 600 level admin
  hard-stop-after 30s
defaults
  mode tcp
  timeout connect 10s
  timeout client 1h
  timeout server 1h
  timeout check 5s
  option tcpka
"""
        # A range describes available forwarding, including services that may
        # start later. Track one transport listener per link rather than running
        # tens of thousands of repeated health probes against the same tunnel.
        tracked = {}
        for backends in pool.values():
            for host, port, link, group in backends:
                if link.get("range_mapping"):
                    tracked.setdefault(f'{link["slot"]}_{group}', (host, port))
        for slot, (host, port) in tracked.items():
            config += f"backend transport_{slot}\n  server ready {host}:{port} check inter 3s fall 3 rise 2\n"
            plan["checks"].append({"host": host, "port": port})
        for public, backends in sorted(pool.items()):
            policy = backends[0][2]["policy"]
            config += f'listen public_{public}\n  bind {public_address}:{public}\n  balance {"roundrobin" if policy=="failover" else policy}\n'
            for i, (host, port, link, group) in enumerate(
                sorted(backends, key=lambda x: x[2]["slot"])
            ):
                health = (
                    f'track transport_{link["slot"]}_{group}/ready'
                    if link.get("range_mapping")
                    else "check inter 3s fall 3 rise 2"
                )
                config += (
                    f'  server edge_{link["slot"]} {host}:{port} weight {link["weight"]} {health}'
                    + (" backup" if policy == "failover" and i else "")
                    + "\n"
                )
                if not link.get("range_mapping"):
                    plan["checks"].append({"host": host, "port": port})
            plan["listeners"].append(public)
            plan["sockets"].append({"address": public_address, "protocol": "tcp", "port": public})
            plan["firewall"].append(
                {
                    "protocol": "tcp",
                    "source": "0.0.0.0/0",
                    "destination": public_address,
                    "port": public,
                }
            )
        relays = plan.pop("relay")
        for relay in relays:
            config += relay_config(relay)
            plan["listeners"].append(relay["port"])
        if pool or relays:
            plan["files"]["haproxy.cfg"] = config
            plan["units"][f"meshdock-{namespace}-router.service"] = service(
                f"/usr/sbin/haproxy -Ws -f /var/lib/meshdock/{namespace}/current/haproxy.cfg -p /run/meshdock-{namespace}-haproxy.pid",
                extra="ExecReload=/bin/kill -USR2 $MAINPID\nKillMode=mixed",
                kind="notify",
            )
        if plan["network_interfaces"]:
            gre_units = [name for name in plan["units"] if name.endswith("-gre.service")]
            unit = service(
                f"/usr/bin/python3 /var/lib/meshdock/{namespace}/agent.py --network-up {namespace}",
                extra=f"RemainAfterExit=yes\nExecStopPost=/usr/bin/python3 /var/lib/meshdock/{namespace}/agent.py --network-down {namespace}",
                kind="oneshot",
            )
            plan["units"][f"meshdock-{namespace}-network.service"] = unit.replace(
                "After=network-online.target",
                "After=network-online.target "
                + " ".join(gre_units)
                + "\nRequires="
                + " ".join(gre_units),
            )
        validate_bindings(plan)
        if plan["firewall"]:
            from .firewall import script

            plan["files"]["firewall.sh"] = script(namespace, plan["firewall"])
            plan["units"][f"meshdock-{namespace}-firewall.service"] = service(
                f"/bin/sh /var/lib/meshdock/{namespace}/current/firewall.sh",
                extra="RemainAfterExit=yes",
                kind="oneshot",
            )
        # Allow the router's listeners plus two descriptors per active proxy
        # connection. This is per-process headroom, not a promise of throughput.
        forwards = plan.pop("forward_count")
        nofile = max(65536, 2 * forwards + 4096)
        if pool or relays:
            nofile = max(nofile, len(plan["sockets"]) + 2 * 65536 + 4096)
        nofile = 1 << (nofile - 1).bit_length()
        plan["resources"] = {
            "listeners": len(plan["sockets"]),
            "nofile": nofile if plan["units"] else 0,
            "descriptor_budget": (
                len(plan["sockets"]) + 2 * forwards + 4096 if plan["units"] else 0
            ),
        }
        for name, unit in plan["units"].items():
            if "Type=oneshot\n" not in unit:
                plan["units"][name] = unit.replace("LimitNOFILE=65536", f"LimitNOFILE={nofile}")
        plan["binaries"] = sorted(set(plan["binaries"]))
        plan["listeners"] = sorted(set(plan["listeners"]))
    return plans


def validate_bindings(plan):
    seen = set()
    for endpoint in plan["sockets"]:
        identity = (endpoint["address"], endpoint["protocol"], endpoint["port"])
        if identity in seen:
            raise AppError("control_port_conflict")
        seen.add(identity)
        for interval in plan["forwarded_ranges"]:
            if (
                endpoint["address"] == interval["address"]
                and endpoint["protocol"] == interval["protocol"]
                and interval["start"] <= endpoint["port"] <= interval["end"]
            ):
                raise AppError("control_port_conflict")


def relay_config(relay):
    """Render an owned relay with mandatory verification for upstream TLS."""
    tls = ""
    if certificate := relay.get("certificate"):
        tls = f" ssl crt {certificate} ssl-min-ver TLSv1.2"
    upstream_tls = ""
    if ca := relay.get("trusted_ca"):
        upstream_tls = (
            f" ssl verify required ca-file {ca} verifyhost {TLS_SERVER_NAME}"
            f" sni str({TLS_SERVER_NAME}) check-sni {TLS_SERVER_NAME} ssl-min-ver TLSv1.2"
        )
    return (
        f'listen relay_{relay["name"]}\n'
        f'  bind {relay["bind"]}:{relay["port"]}{tls}\n'
        f'  server target {relay["host"]}:{relay["target"]}{upstream_tls} check inter 3s\n'
    )
