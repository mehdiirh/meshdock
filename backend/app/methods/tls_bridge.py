"""Owned TLS bridges for upstreams without a verifying TLS client.

The public wire protocol remains TLS; plaintext is restricted to the link's
loopback address. Certificate and hostname verification are never optional.
"""


def identity(context, plan, *, private=False):
    name = context.filename
    plan["files"][name + "-ca.crt"] = context.secrets["tls_cert"]
    if private:
        plan["files"][name + "-tls.pem"] = context.secrets["tls_key"] + context.secrets["tls_cert"]
    return f"{context.root}/{name}"


def verified_client(context, plan):
    root = identity(context, plan)
    port = context.auxiliary(0, "exit")
    plan["relay"].append(
        {
            "name": f"tls_client_{context.link['slot']}",
            "bind": context.bind_address,
            "port": port,
            "host": context.entry["address"],
            "target": context.control,
            "trusted_ca": root + "-ca.crt",
        }
    )
    return f"{context.bind_address}:{port}"


def tls_server(context, plan):
    root = identity(context, plan, private=True)
    port = context.auxiliary(0)
    plan["relay"].append(
        {
            "name": f"tls_server_{context.link['slot']}",
            "bind": context.entry["address"],
            "port": context.control,
            "host": context.bind_address,
            "target": port,
            "certificate": root + "-tls.pem",
        }
    )
    plan["listeners"].append(port)
    return f"{context.bind_address}:{port}"
