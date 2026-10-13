import json

from .base import Adapter, service


class Rathole(Adapter):
    metadata = {
        "id": "rathole",
        "name": "Rathole",
        "encrypted": True,
        "direction": "exit-to-entry",
        "protocols": ["tcp"],
        "requirements": ["outbound-tcp"],
    }

    def configure(self, context, entry, exit):
        server = f'[server]\nbind_addr = "0.0.0.0:{context.control}"\n[server.transport]\ntype = "noise"\n[server.transport.noise]\nlocal_private_key = {json.dumps(context.secrets["noise_private"])}\n'
        client = f'[client]\nremote_addr = "{context.entry["address"]}:{context.control}"\n[client.transport]\ntype = "noise"\n[client.transport.noise]\nremote_public_key = {json.dumps(context.secrets["noise_public"])}\n'
        for index, port in enumerate(context.link["ports"]):
            name = f's{context.link["slot"]}_{index}'
            token = json.dumps(context.secrets["token"])
            server += f'[server.services.{name}]\ntoken = {token}\nbind_addr = "127.0.0.1:{context.internal(index)}"\n'
            client += f'[client.services.{name}]\ntoken = {token}\nlocal_addr = "{port["host"]}:{port["target"]}"\n'
            entry["backends"].append(
                (port, "127.0.0.1", context.internal(index), context.link)
            )
            entry["listeners"].append(context.internal(index))
        entry["files"][context.filename + ".toml"] = server
        exit["files"][context.filename + ".toml"] = client
        for plan in (entry, exit):
            plan["binaries"].append("rathole")
            plan["units"][context.tag + ".service"] = service(
                f"/var/lib/tunnel-manager/{context.namespace}/bin/rathole {context.root}/{context.filename}.toml"
            )
        entry["firewall"].append(
            {
                "protocol": "tcp",
                "source": context.exit["address"],
                "port": context.control,
            }
        )
        entry["listeners"].append(context.control)
