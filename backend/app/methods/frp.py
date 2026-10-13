import json
from typing import Literal

from ..tls import TLS_SERVER_NAME
from .base import Adapter, service
from .options import Options, option
from .tls_bridge import identity, tls_server

STREAM = {"transport": ["tcp", "kcp", "websocket", "wss"]}
QUIC = {"transport": ["quic"]}


class FrpOptions(Options):
    transport: Literal["tcp", "kcp", "quic", "websocket", "wss"] = option("wss")
    tcp_mux: bool = option(True, when=STREAM)
    quic_keepalive: int = option(10, ge=1, le=300, unit="seconds", when=QUIC)
    quic_idle_timeout: int = option(30, ge=2, le=3600, unit="seconds", when=QUIC)
    quic_max_streams: int = option(100000, ge=1, le=1000000, when=QUIC)
    tcp_mux_keepalive: int = option(
        30, ge=1, le=300, unit="seconds", when={**STREAM, "tcp_mux": [True]}
    )
    pool_count: int = option(0, ge=0, le=100, scope="client")
    dial_timeout: int = option(10, ge=1, le=300, scope="client", unit="seconds")
    heartbeat_interval: int = option(10, ge=1, le=300, scope="client", unit="seconds")
    heartbeat_timeout: int = option(90, ge=2, le=3600, unit="seconds")
    rules = [
        {"left": "heartbeat_interval", "operator": "lt", "right": "heartbeat_timeout"},
        {"left": "quic_keepalive", "operator": "lt", "right": "quic_idle_timeout", "when": QUIC},
    ]


class FrpWSS(Adapter):
    options_model = FrpOptions
    auxiliary_count = 1
    transports = {
        name: {
            "encrypted": True,
            "control_protocols": ["tcp", "udp"] if name in ("kcp", "quic") else ["tcp"],
            "tls_mode": "verified_native",
        }
        for name in FrpOptions.model_fields["transport"].annotation.__args__
    }

    def auxiliary_counts(self, link):
        return int(self.options(link).transport == "wss"), 0

    metadata = {
        "id": "frp_wss",
        "name": "FRP",
        "encrypted": True,
        "direction": "exit-to-entry",
        "protocols": ["tcp"],
        "requirements": ["outbound-tcp", "pinned-private-tls"],
        "priority": 1,
        "score": 3.65,
        "caveat": "private_tls",
    }

    def configure(self, context, entry, exit):
        options = self.options(context.link)
        common = f"transport.heartbeatTimeout = {options.heartbeat_timeout}\n"
        if options.transport == "quic":
            common += (
                f"transport.quic.keepalivePeriod = {options.quic_keepalive}\n"
                f"transport.quic.maxIdleTimeout = {options.quic_idle_timeout}\n"
                f"transport.quic.maxIncomingStreams = {options.quic_max_streams}\n"
            )
        else:
            common += f"transport.tcpMux = {json.dumps(options.tcp_mux)}\n"
            if options.tcp_mux:
                common += f"transport.tcpMuxKeepaliveInterval = {options.tcp_mux_keepalive}\n"
        name = context.filename
        token = json.dumps(context.secrets["token"])
        identity(context, exit)
        bind_address = context.entry["address"]
        bind_port = context.control
        server_tls = "transport.tls.force = true\n"
        if options.transport == "wss":
            tls_server(context, entry)
            bind_address = context.bind_address
            bind_port = context.auxiliary(0)
            server_tls = "transport.tls.force = false\n"
        else:
            entry["files"][name + "-tls.crt"] = context.secrets["tls_cert"]
            entry["files"][name + "-tls.key"] = context.secrets["tls_key"]
            server_tls += (
                f'transport.tls.certFile = "{context.root}/{name}-tls.crt"\n'
                f'transport.tls.keyFile = "{context.root}/{name}-tls.key"\n'
            )
        udp_listener = ""
        if options.transport in ("kcp", "quic"):
            key = "kcpBindPort" if options.transport == "kcp" else "quicBindPort"
            udp_listener = f"{key} = {context.control}\n"
            entry["udp_listeners"].append(context.control)
            entry["firewall"].append(
                {
                    "protocol": "udp",
                    "source": context.exit["address"],
                    "destination": context.entry["address"],
                    "port": context.control,
                }
            )
        ports = ", ".join(
            "{ single = " + str(context.internal(i)) + " }"
            for i in range(len(context.link["ports"]))
        )
        entry["files"][name + ".toml"] = f"""bindAddr = "{bind_address}"
bindPort = {bind_port}
{udp_listener}
proxyBindAddr = "{context.bind_address}"
auth.method = "token"
auth.token = {token}
allowPorts = [{ports}]
{server_tls}transport.maxPoolCount = {max(5, options.pool_count)}
"""
        entry["files"][name + ".toml"] += common
        client = f"""serverAddr = "{context.entry['address']}"
serverPort = {context.control}
loginFailExit = false
auth.method = "token"
auth.token = {token}
transport.protocol = "{options.transport}"
transport.tls.enable = true
transport.tls.disableCustomTLSFirstByte = true
transport.tls.trustedCaFile = "{context.root}/{name}-ca.crt"
transport.tls.serverName = "{TLS_SERVER_NAME}"
transport.poolCount = {options.pool_count}
transport.dialServerTimeout = {options.dial_timeout}
transport.heartbeatInterval = {options.heartbeat_interval}
"""
        client += common
        for index, port in enumerate(context.link["ports"]):
            client += f"""\n[[proxies]]
name = "port-{index}"
type = "tcp"
localIP = "{port['host']}"
localPort = {port['target']}
remotePort = {context.internal(index)}
"""
            entry["listeners"].append(context.internal(index))
            entry["backends"].append(
                (port, context.bind_address, context.internal(index), context.link)
            )
        exit["files"][name + ".toml"] = client
        for plan, binary in ((entry, "frps"), (exit, "frpc")):
            plan["binaries"].append(binary)
            plan["units"][context.tag + ".service"] = service(
                f"/var/lib/meshdock/{context.namespace}/bin/{binary} -c {context.root}/{name}.toml"
            )
        entry["listeners"].append(context.control)
        entry["firewall"].append(
            {
                "protocol": "tcp",
                "source": context.exit["address"],
                "port": context.control,
                "destination": context.entry["address"],
            }
        )
