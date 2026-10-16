"""Compact mapping intent shared by validation, allocation and transport adapters."""

import re


def bounds(value):
    if isinstance(value, bool) or not re.fullmatch(r"[0-9]{1,5}(?:-[0-9]{1,5})?", str(value)):
        raise ValueError("port_range")
    parts = [int(part) for part in str(value).split("-")]
    first, last = parts[0], parts[-1]
    if not 1 <= first <= last <= 65535:
        raise ValueError("port_range")
    return first, last


def normalize(value):
    first, last = bounds(value)
    return first if first == last else f"{first}-{last}"


def segments(mapping):
    """Yield public/target intervals, retaining offsets across excluded intervals."""
    first, last = bounds(mapping["public"])
    target, _ = bounds(mapping["target"])
    cursor = first
    exclusions = sorted(bounds(value) for value in mapping.get("exclude", []))
    for start, end in exclusions:
        if start > cursor:
            yield cursor, start - 1, target + cursor - first, target + start - 1 - first
        cursor = max(cursor, end + 1)
    if cursor <= last:
        yield cursor, last, target + cursor - first, target + last - first


def protocols(mapping):
    value = mapping.get("protocol", "tcp")
    return ("tcp", "udp") if value == "both" else (value,)


def count(mappings):
    return sum(
        (end - start + 1) * len(protocols(p)) for p in mappings for start, end, _, _ in segments(p)
    )


def expand(mappings):
    return [
        {
            "public": public,
            "target": target + public - start,
            "host": mapping["host"],
            "protocol": protocol,
        }
        for mapping in mappings
        for protocol in protocols(mapping)
        for start, end, target, _ in segments(mapping)
        for public in range(start, end + 1)
    ]


def contains(mapping, port):
    return any(start <= port <= end for start, end, _, _ in segments(mapping))


def overlaps(left, right):
    return bool(set(protocols(left)) & set(protocols(right))) and any(
        max(a, c) <= min(b, d) for a, b, _, _ in segments(left) for c, d, _, _ in segments(right)
    )
