"""Allowlisted health diagnostics shared by SSH results and translated reports."""

import json
import re
from ipaddress import ip_address

from .i18n import translate


def health_details(value):
    """Discard remote output and unknown fields before persisting or displaying them."""
    if not isinstance(value, dict):
        return {}
    check = value.get("check")
    fields = {"check": check}
    try:
        if check == "service":
            unit = value.get("unit", "")
            if not isinstance(unit, str) or not re.fullmatch(
                r"meshdock-[a-z0-9-]{1,100}\.service", unit
            ):
                return {}
            fields["unit"] = unit
        elif check == "gre_peer":
            interface = value.get("interface", "")
            if not isinstance(interface, str) or not re.fullmatch(r"md[a-z0-9]{1,13}", interface):
                return {}
            fields.update(interface=interface, peer=str(ip_address(value["peer"])))
        elif check == "firewall":
            table, parent, chain = (value.get(k, "") for k in ("table", "parent", "chain"))
            if table not in ("filter", "nat", "mangle") or parent not in (
                "INPUT",
                "OUTPUT",
                "FORWARD",
                "PREROUTING",
                "POSTROUTING",
            ):
                return {}
            if not isinstance(chain, str) or not re.fullmatch(r"MESHDOCK_[A-Z0-9_]{1,48}", chain):
                return {}
            fields.update(table=table, parent=parent, chain=chain)
        elif check in ("connection", "listener"):
            address = value.get("address", "")
            if not isinstance(address, str):
                return {}
            try:
                address = str(ip_address(address))
            except ValueError:
                if check != "connection" or not re.fullmatch(r"[A-Za-z0-9.-]{1,253}", address):
                    return {}
            port = value.get("port")
            if type(port) is not int or not 1 <= port <= 65535:
                return {}
            fields.update(address=address, port=port)
            if check == "listener":
                missing = value.get("missing")
                if (
                    value.get("protocol") not in ("tcp", "udp")
                    or type(missing) is not int
                    or missing < 1
                ):
                    return {}
                fields.update(protocol=value["protocol"], missing=missing)
        elif check == "listener_scan":
            if value.get("protocol") not in ("tcp", "udp"):
                return {}
            fields["protocol"] = value["protocol"]
        else:
            return {}
    except (ValueError, TypeError, KeyError):
        return {}
    return fields


def report(code, detail, language="en"):
    """Retain legacy error codes while explaining the specific failing check."""
    fallback = {
        "message": translate(code, language),
        "hint": (
            translate("health_unknown_hint", language)
            if code in ("health_failed", "health_retry")
            else None
        ),
    }
    if code not in ("health_failed", "health_retry"):
        return fallback
    try:
        value = json.loads(detail) if isinstance(detail, str) else detail
    except (ValueError, TypeError):
        return fallback
    safe = health_details(value)
    if not safe:
        return fallback
    check = safe["check"]
    message = translate("health_" + check + "_message", language).format(**safe)
    if code == "health_retry":
        attempt, limit = value.get("health_attempt"), value.get("health_attempts")
        if type(attempt) is int and type(limit) is int and 1 <= attempt < limit <= 100:
            message = translate("health_retry_message", language).format(
                attempt=attempt, limit=limit, message=message
            )
    return {"message": message, "hint": translate("health_" + check + "_hint", language)}
