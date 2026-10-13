"""Deterministic allocations belong to a deployment plan, never to a reserved public band."""

from collections import defaultdict
from itertools import chain

from .methods import REGISTRY
from .ports import bounds, contains, expand, segments
from .security import AppError


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
            targets[(link["exit_id"], mapping["host"])].extend(
                (start, end) for _, _, start, end in segments(mapping)
            )
        adapter = REGISTRY[link["method"]]
        adapter.validate_mappings(link)
        if adapter.control_protocol and link.get("control_port"):
            server = (
                link["entry_id"]
                if adapter.metadata["direction"] == "exit-to-entry"
                else link["exit_id"]
            )
            occupied.add((server, adapter.control_protocol, link["control_port"]))

    for link in links:
        adapter = REGISTRY[link["method"]]
        protocol = adapter.control_protocol
        if protocol:
            server = (
                link["entry_id"]
                if adapter.metadata["direction"] == "exit-to-entry"
                else link["exit_id"]
            )
            destination_ports = targets[(server, servers[server]["address"])]
            if link.get("control_port"):
                if protocol == "tcp" and any(
                    start <= link["control_port"] <= end for start, end in destination_ports
                ):
                    raise AppError("control_port_conflict")
                link["allocated_control"] = link["control_port"]
            else:
                candidates = chain([20000 + link["slot"]], range(1024, 65536), range(1, 1024))
                port = next(
                    (
                        p
                        for p in candidates
                        if (server, protocol, p) not in occupied
                        and (
                            protocol != "tcp"
                            or (
                                p != servers[server]["ssh_port"]
                                and not any(contains(mapping, p) for mapping in public[server])
                                and not any(start <= p <= end for start, end in destination_ports)
                            )
                        )
                    ),
                    None,
                )
                if port is None:
                    raise AppError("port_capacity")
                occupied.add((server, protocol, port))
                link["allocated_control"] = port

    # Separate loopback addresses give each transport its own port space. Build
    # the free-port iterator once; restarting a scan per port becomes quadratic.
    internal = defaultdict(set)
    for link in links:
        adapter = REGISTRY[link["method"]]
        if adapter.kernel_mapping(link):
            link["internal_ports"] = []
            continue
        link["range_mapping"] = any(
            bounds(mapping["public"])[0] != bounds(mapping["public"])[1] or mapping.get("exclude")
            for mapping in link["ports"]
        )
        link["ports"] = expand(link["ports"])
        server = link["exit_id"] if adapter.internal_on_exit else link["entry_id"]
        bind = adapter.internal_address(link)
        link["internal_address"] = bind
        key = (server, bind)
        unavailable = set(internal[key])
        # A wildcard management listener must never be shadowed.
        unavailable.add(servers[server]["ssh_port"])
        for first, last in targets[key]:
            unavailable.update(range(first, last + 1))
        available = (p for p in chain(range(30000, 65536), range(1, 30000)) if p not in unavailable)
        selected = []
        for index in range(len(link["ports"]) + adapter.auxiliary_count):
            preferred = 30000 + (link["slot"] - 1) * 16 + index
            if preferred <= 65535 and preferred not in unavailable:
                port = preferred
            else:
                port = next(available, None)
            if port is None:
                raise AppError("port_capacity")
            selected.append(port)
            unavailable.add(port)
        internal[key].update(selected)
        link["internal_ports"] = selected[: len(link["ports"])]
        link["auxiliary_ports"] = selected[len(link["ports"]) :]
    return links
