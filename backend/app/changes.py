"""Stable per-link change attribution, excluding presentation-only server edits."""

from .allocation import allocate


def affected_links(previous, desired):
    def signatures(snapshot):
        if not snapshot.get("servers"):
            return {}
        servers = {s["id"]: s for s in snapshot["servers"]}
        result = {}
        for link in allocate(snapshot):
            endpoints = [
                {
                    key: servers[link[side]].get(key)
                    for key in (
                        "host",
                        "ssh_port",
                        "address",
                        "credential_id",
                        "fingerprint",
                        "ssh_jump",
                    )
                }
                for side in ("entry_id", "exit_id")
            ]
            result[link["id"]] = link, endpoints
        return result

    old, new = signatures(previous), signatures(desired)
    return sorted(id for id in old.keys() | new.keys() if old.get(id) != new.get(id))
