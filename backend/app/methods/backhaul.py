import json

from .base import Adapter, service


class Backhaul(Adapter):
    metadata = {
        "id": "backhaul",
        "name": "Backhaul",
        "encrypted": False,
        "direction": "exit-to-entry",
        "protocols": ["tcp"],
        "requirements": ["outbound-tcp"],
    }

    def configure(self, context, entry, exit):
        ports = [
            f'127.0.0.1:{context.internal(index)}={port["host"]}:{port["target"]}'
            for index, port in enumerate(context.link["ports"])
        ]
        common = f'transport = "tcp"\ntoken = {json.dumps(context.secrets["token"])}\nnodelay = true\nkeepalive_period = 30\nskip_optz = true\nsniffer = false\nweb_port = 0\n'
        entry["files"][context.filename + ".toml"] = (
            f'[server]\nbind_addr = "0.0.0.0:{context.control}"\n'
            + common
            + "heartbeat = 10\nchannel_size = 2048\nports = "
            + json.dumps(ports)
            + "\n"
        )
        exit["files"][context.filename + ".toml"] = (
            f'[client]\nremote_addr = "{context.entry["address"]}:{context.control}"\n'
            + common
            + "connection_pool = 8\naggressive_pool = false\ndial_timeout = 10\nretry_interval = 3\n"
        )
        for plan in (entry, exit):
            plan["binaries"].append("backhaul")
            plan["units"][context.tag + ".service"] = service(
                f"/var/lib/tunnel-manager/{context.namespace}/bin/backhaul -c {context.root}/{context.filename}.toml"
            )
        entry["firewall"].append(
            {
                "protocol": "tcp",
                "source": context.exit["address"],
                "port": context.control,
            }
        )
        entry["listeners"].append(context.control)
        for index, port in enumerate(context.link["ports"]):
            entry["listeners"].append(context.internal(index))
            entry["backends"].append((port, "127.0.0.1", context.internal(index), context.link))
