import json

from ..tls import TLS_SERVER_NAME
from .base import Adapter, service


class FrpWSS(Adapter):
    auxiliary_count = 1

    metadata = {
        "id": "frp_wss",
        "name": "FRP · WSS",
        "encrypted": True,
        "direction": "exit-to-entry",
        "protocols": ["tcp"],
        "requirements": ["outbound-tcp", "pinned-private-tls"],
        "priority": 1,
        "score": 3.65,
        "caveat": "private_tls",
    }

    def configure(self, context, entry, exit):
        name = context.filename
        token = json.dumps(context.secrets["token"])
        for plan in (entry, exit):
            plan["files"][name + "-ca.crt"] = context.secrets["tls_cert"]
        # frps accepts plaintext WebSocket upgrades. The owned HAProxy listener
        # terminates verified WSS and forwards only over loopback to frps.
        entry["files"][name + "-tls.pem"] = context.secrets["tls_key"] + context.secrets["tls_cert"]
        websocket_port = context.auxiliary(0)
        entry["relay"].append(
            {
                "name": f"wss_{context.link['slot']}",
                "bind": context.entry["address"],
                "port": context.control,
                "destination": context.entry["address"],
                "host": context.bind_address,
                "target": websocket_port,
                "certificate": f"{context.root}/{name}-tls.pem",
            }
        )
        ports = ", ".join(
            "{ single = " + str(context.internal(i)) + " }"
            for i in range(len(context.link["ports"]))
        )
        entry["files"][name + ".toml"] = f"""bindAddr = "{context.bind_address}"
bindPort = {websocket_port}
proxyBindAddr = "{context.bind_address}"
auth.method = "token"
auth.token = {token}
allowPorts = [{ports}]
transport.tls.force = false
"""
        client = f"""serverAddr = "{context.entry['address']}"
serverPort = {context.control}
loginFailExit = false
auth.method = "token"
auth.token = {token}
transport.protocol = "wss"
transport.tls.enable = true
transport.tls.disableCustomTLSFirstByte = true
transport.tls.trustedCaFile = "{context.root}/{name}-ca.crt"
transport.tls.serverName = "{TLS_SERVER_NAME}"
"""
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
                f"/var/lib/tunnel-manager/{context.namespace}/bin/{binary} -c {context.root}/{name}.toml"
            )
        entry["listeners"].extend([context.control, websocket_port])
        entry["firewall"].append(
            {
                "protocol": "tcp",
                "source": context.exit["address"],
                "port": context.control,
                "destination": context.entry["address"],
            }
        )
