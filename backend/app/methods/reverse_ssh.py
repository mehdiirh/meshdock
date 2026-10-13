from .base import Adapter, service


class ReverseSSH(Adapter):
    metadata = {
        "id": "reverse_ssh",
        "name": "Reverse SSH",
        "encrypted": True,
        "direction": "exit-to-entry",
        "protocols": ["tcp"],
        "requirements": ["outbound-tcp"],
    }

    def configure(self, context, entry, exit):
        name = context.filename
        entry["files"][name + "-host"] = context.secrets["host_private"]
        options = ",".join(
            f'permitlisten="127.0.0.1:{context.internal(index)}"'
            for index in range(len(context.link["ports"]))
        )
        entry["files"][name + "-authorized"] = (
            "restrict,port-forwarding," + options + " " + context.secrets["client_public"] + "\n"
        )
        entry["files"][name + "-sshd.conf"] = f"""Port {context.control}
ListenAddress 0.0.0.0
HostKey {context.root}/{name}-host
PidFile /run/{context.tag}.pid
AuthorizedKeysFile {context.root}/{name}-authorized
PermitRootLogin prohibit-password
PasswordAuthentication no
KbdInteractiveAuthentication no
AuthenticationMethods publickey
UsePAM no
AllowUsers root
AllowTcpForwarding remote
GatewayPorts no
PermitTTY no
X11Forwarding no
AllowAgentForwarding no
PermitUserRC no
ForceCommand /usr/sbin/nologin
LogLevel ERROR
"""
        entry["units"][context.tag + ".service"] = service(
            f"/usr/sbin/sshd -D -e -f {context.root}/{name}-sshd.conf"
        )
        exit["files"][name + "-key"] = context.secrets["client_private"]
        peer = context.entry["address"]
        known_host = peer if context.control == 22 else f"[{peer}]:{context.control}"
        exit["files"][name + "-known"] = known_host + " " + context.secrets["host_public"] + "\n"
        forwards = " ".join(
            f'-R 127.0.0.1:{context.internal(index)}:{port["host"]}:{port["target"]}'
            for index, port in enumerate(context.link["ports"])
        )
        exit["units"][context.tag + ".service"] = service(
            f'/usr/bin/ssh -NT -F /dev/null -i {context.root}/{name}-key -o UserKnownHostsFile={context.root}/{name}-known -o StrictHostKeyChecking=yes -o IdentitiesOnly=yes -o BatchMode=yes -o ExitOnForwardFailure=yes -o ServerAliveInterval=15 -o ServerAliveCountMax=3 -o ConnectTimeout=10 -p {context.control} {forwards} root@{context.entry["address"]}'
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
