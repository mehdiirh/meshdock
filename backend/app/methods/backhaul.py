import json
from typing import Literal

from .base import Adapter, service
from .options import Options, option, toml_values

MUX = {"transport": ["tcpmux", "wsmux"]}


class BackhaulOptions(Options):
    transport: Literal["tcp", "tcpmux", "ws", "wsmux"] = option("tcp")
    nodelay: bool = option(True)
    keepalive_period: int = option(30, ge=1, le=3600, unit="seconds")
    heartbeat: int = option(10, ge=1, le=300, scope="server", unit="seconds")
    channel_size: int = option(2048, ge=1, le=65536, scope="server")
    connection_pool: int = option(8, ge=1, le=1024, scope="client")
    aggressive_pool: bool = option(False, scope="client")
    dial_timeout: int = option(10, ge=1, le=300, scope="client", unit="seconds")
    retry_interval: int = option(3, ge=1, le=300, scope="client", unit="seconds")
    mux_con: int = option(8, ge=1, le=256, scope="server", when=MUX)
    mux_version: Literal[1, 2] = option(1, when=MUX)
    mux_framesize: int = option(32768, ge=512, le=65535, unit="bytes", when=MUX)
    mux_recievebuffer: int = option(4194304, ge=65536, le=268435456, unit="bytes", when=MUX)
    mux_streambuffer: int = option(65536, ge=65536, le=268435456, unit="bytes", when=MUX)
    rules = [
        {"left": "mux_streambuffer", "operator": "lte", "right": "mux_recievebuffer", "when": MUX}
    ]


class Backhaul(Adapter):
    options_model = BackhaulOptions
    metadata = {
        "id": "backhaul",
        "name": "Backhaul",
        "encrypted": False,
        "direction": "exit-to-entry",
        "protocols": ["tcp"],
        "requirements": ["outbound-tcp"],
    }

    def configure(self, context, entry, exit):
        options = self.options(context.link)
        ports = [
            f'{context.bind_address}:{context.internal(index)}={port["host"]}:{port["target"]}'
            for index, port in enumerate(context.link["ports"])
        ]
        common = f'token = {json.dumps(context.secrets["token"])}\nskip_optz = true\nsniffer = false\nweb_port = 0\n'
        entry["files"][context.filename + ".toml"] = (
            f'[server]\nbind_addr = "{context.entry["address"]}:{context.control}"\n'
            + common
            + toml_values(options.values("server"))
            + "ports = "
            + json.dumps(ports)
            + "\n"
        )
        exit["files"][context.filename + ".toml"] = (
            f'[client]\nremote_addr = "{context.entry["address"]}:{context.control}"\n'
            + common
            + toml_values(options.values("client"))
        )
        for plan in (entry, exit):
            plan["binaries"].append("backhaul")
            plan["units"][context.tag + ".service"] = service(
                f"/var/lib/meshdock/{context.namespace}/bin/backhaul -c {context.root}/{context.filename}.toml"
            )
        entry["firewall"].append(
            {
                "protocol": "tcp",
                "source": context.exit["address"],
                "port": context.control,
                "destination": context.entry["address"],
            }
        )
        entry["listeners"].append(context.control)
        for index, port in enumerate(context.link["ports"]):
            entry["listeners"].append(context.internal(index))
            entry["backends"].append(
                (port, context.bind_address, context.internal(index), context.link)
            )
