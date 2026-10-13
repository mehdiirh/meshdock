"""Deterministic allocations belong to a deployment plan, never to a reserved public band."""

from collections import defaultdict
from ipaddress import IPv4Address
from itertools import chain

from .methods import REGISTRY
from .ports import contains, expand
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
        targets[link["exit_id"]].extend(
            p for p in link["ports"] if IPv4Address(p["host"]).is_loopback
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
            if link.get("control_port"):
                link["allocated_control"] = link["control_port"]
            else:
                candidates = chain([20000 + link["slot"]], range(1024, 65536))
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
                            )
                        )
                    ),
                    None,
                )
                if port is None:
                    raise AppError("port_capacity")
                occupied.add((server, protocol, port))
                link["allocated_control"] = port

    # Socket adapters bind application listeners to the public IPv4 and internal
    # listeners to loopback. Port numbers can therefore coexist on distinct IPs.
    internal = defaultdict(set)
    for link in links:
        adapter = REGISTRY[link["method"]]
        if adapter.kernel_mapping(link):
            link["internal_ports"] = []
            continue
        link["ports"] = expand(link["ports"])
        server = link["exit_id"] if adapter.internal_on_exit else link["entry_id"]
        bind = adapter.internal_address(link)
        key = (server, bind)
        selected = []
        for index in range(len(link["ports"]) + adapter.auxiliary_count):
            preferred = 30000 + (link["slot"] - 1) * 16 + index if index < 16 else 46000 + index
            candidates = chain([preferred], range(30000, 65536), range(1024, 30000))
            port = next(
                (
                    p
                    for p in candidates
                    if p <= 65535
                    and p not in internal[key]
                    and p != servers[server]["ssh_port"]
                    and not any(
                        contains(
                            {
                                **mapping,
                                "public": mapping["target"],
                                "target": mapping["target"],
                                "exclude": [],
                            },
                            p,
                        )
                        for mapping in (targets[server] if bind == "127.0.0.1" else [])
                    )
                ),
                None,
            )
            if port is None:
                raise AppError("port_capacity")
            selected.append(port)
            internal[key].add(port)
        link["internal_ports"] = selected[: len(link["ports"])]
        link["auxiliary_ports"] = selected[len(link["ports"]) :]
    return links
