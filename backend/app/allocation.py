"""Deterministic allocations belong to a deployment plan, never to a reserved public band."""

from collections import defaultdict
from itertools import chain

from .methods import REGISTRY
from .ports import bounds, contains, expand, segments, protocols as payload_protocols
from .security import AppError


def free_ports(unavailable):
    return (p for p in chain(range(30000, 65536), range(1, 30000)) if p not in unavailable)


def allocate(snapshot):
    servers = {server["id"]: server for server in snapshot["servers"]}
    links = sorted(
        (dict(link) for link in snapshot["links"] if link["enabled"]), key=lambda link: link["slot"]
    )
    occupied = set()
    public = defaultdict(list)
    targets = defaultdict(list)
    for link in links:
        public[link["entry_id"]].extend(link["ports"])
        for mapping in link["ports"]:
            for protocol in payload_protocols(mapping):
                targets[(link["exit_id"], mapping["host"], protocol)].extend(
                    (start, end) for _, _, start, end in segments(mapping)
                )
        adapter = REGISTRY[link["method"]]
        adapter.validate_mappings(link)
        if adapter.control_protocols(link) and link.get("control_port"):
            server = (
                link["entry_id"]
                if adapter.metadata["direction"] == "exit-to-entry"
                else link["exit_id"]
            )
            for protocol in adapter.control_protocols(link):
                occupied.add((server, protocol, link["control_port"]))

    for link in links:
        adapter = REGISTRY[link["method"]]
        protocols = adapter.control_protocols(link)
        if protocols:
            server = (
                link["entry_id"]
                if adapter.metadata["direction"] == "exit-to-entry"
                else link["exit_id"]
            )
            destination_ports = [
                interval
                for protocol in protocols
                for interval in targets[(server, servers[server]["address"], protocol)]
            ]
            if link.get("control_port"):
                if any(start <= link["control_port"] <= end for start, end in destination_ports):
                    raise AppError("control_port_conflict")
                link["allocated_control"] = link["control_port"]
            else:
                candidates = chain([20000 + link["slot"]], range(1024, 65536), range(1, 1024))
                port = next(
                    (
                        p
                        for p in candidates
                        if all((server, protocol, p) not in occupied for protocol in protocols)
                        and ("tcp" not in protocols or p != servers[server]["ssh_port"])
                        and not any(
                            set(protocols) & set(payload_protocols(mapping))
                            and contains(mapping, p)
                            for mapping in public[server]
                        )
                        and not any(start <= p <= end for start, end in destination_ports)
                    ),
                    None,
                )
                if port is None:
                    raise AppError("port_capacity")
                for protocol in protocols:
                    occupied.add((server, protocol, port))
                link["allocated_control"] = port

    # Separate loopback addresses give each transport its own port space. Build
    # the free-port iterator once; restarting a scan per port becomes quadratic.
    internal = defaultdict(set)
    for link in links:
        adapter = REGISTRY[link["method"]]
        if adapter.compact_mapping(link):
            link["internal_ports"] = []
            server = link["exit_id"] if adapter.internal_on_exit else link["entry_id"]
            unavailable = {servers[server]["ssh_port"]}
            for (target_server, _, protocol), intervals in targets.items():
                if target_server == server and protocol == "tcp":
                    for first, last in intervals:
                        unavailable.update(range(first, last + 1))
            for mapping in public[server]:
                if "tcp" not in payload_protocols(mapping):
                    continue
                for first, last, _, _ in segments(mapping):
                    unavailable.update(range(first, last + 1))
            unavailable.update(
                port for host, protocol, port in occupied if host == server and protocol == "tcp"
            )
            adapter.allocate_compact(link, unavailable)
            continue
        link["range_mapping"] = any(
            bounds(mapping["public"])[0] != bounds(mapping["public"])[1] or mapping.get("exclude")
            for mapping in link["ports"]
        )
        link["ports"] = expand(link["ports"])
        if adapter.forwards_per_session:
            for index, mapping in enumerate(link["ports"]):
                mapping["health_group"] = index // adapter.forwards_per_session
        server = link["exit_id"] if adapter.internal_on_exit else link["entry_id"]
        bind = adapter.internal_address(link)
        link["internal_address"] = bind
        entry_aux, exit_aux = adapter.auxiliary_counts(link)
        used = {}
        candidates = {}
        for protocol in ("tcp", "udp"):
            key = (server, bind, protocol)
            unavailable = set(internal[key])
            if protocol == "tcp":
                unavailable.add(servers[server]["ssh_port"])
            for first, last in targets[key]:
                unavailable.update(range(first, last + 1))
            used[protocol] = unavailable
            candidates[protocol] = free_ports(unavailable)

        required_by_protocol = {
            p: adapter.allocation_protocols(link, {"protocol": p}) for p in ("tcp", "udp")
        }
        assigned = {}
        selected = []
        for index, mapping in enumerate(link["ports"]):
            identity = (mapping["public"], mapping["host"], mapping["target"])
            required = required_by_protocol[mapping.get("protocol", "tcp")]
            existing = assigned.get(identity)
            if existing is not None and all(
                existing not in used[p] or (identity, p) in assigned for p in required
            ):
                port = existing
            else:
                preferred = 30000 + (link["slot"] - 1) * 16 + index
                if preferred <= 65535 and all(preferred not in used[p] for p in required):
                    port = preferred
                else:
                    port = next(
                        (
                            p
                            for p in candidates[required[0]]
                            if all(p not in used[proto] for proto in required)
                        ),
                        None,
                    )
                if port is None:
                    raise AppError("port_capacity")
            selected.append(port)
            assigned[identity] = port
            for protocol in required:
                assigned[(identity, protocol)] = port
                used[protocol].add(port)
        auxiliary = []
        for index in range(entry_aux):
            port = next(candidates["tcp"], None)
            if port is None:
                raise AppError("port_capacity")
            auxiliary.append(port)
            used["tcp"].add(port)
        for protocol, unavailable in used.items():
            internal[(server, bind, protocol)].update(unavailable)
        link["internal_ports"] = selected
        link["auxiliary_ports"] = auxiliary
        exit_key = (link["exit_id"], bind, "tcp")
        unavailable_exit = set(internal[exit_key]) | {servers[link["exit_id"]]["ssh_port"]}
        for first, last in targets[exit_key]:
            unavailable_exit.update(range(first, last + 1))
        available_exit = (
            p for p in chain(range(30000, 65536), range(1, 30000)) if p not in unavailable_exit
        )
        selected_exit = []
        for _ in range(exit_aux):
            port = next(available_exit, None)
            if port is None:
                raise AppError("port_capacity")
            selected_exit.append(port)
            unavailable_exit.add(port)
        internal[exit_key].update(selected_exit)
        link["exit_auxiliary_ports"] = selected_exit
    return links
