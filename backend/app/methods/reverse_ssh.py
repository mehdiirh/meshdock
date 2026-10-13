from .base import Adapter, service


class ReverseSSH(Adapter):
    # OpenSSH allocates a channel per remote listener and per active connection.
    # Its 16,384-channel ceiling is per connection, not a limit on this link.
    # Split listeners across sessions, leaving most channels for live traffic.
    forwards_per_session = 4096

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
        address = context.bind_address
        entry["files"][name + "-host"] = context.secrets["host_private"]
        # Limit this key to the link's private listener address. Enumerating every
        # port here would exceed OpenSSH's authorized_keys line-size limit.
        entry["files"][name + "-authorized"] = (
            f'restrict,port-forwarding,permitlisten="{address}:*" '
            + context.secrets["client_public"]
            + "\n"
        )
        entry["files"][name + "-sshd.conf"] = f"""Port {context.control}
ListenAddress {context.entry["address"]}
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
AllowStreamLocalForwarding no
GatewayPorts clientspecified
PermitListen {address}:*
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
        common = f"""Host tunnel
  HostName {peer}
  Port {context.control}
  User root
  IdentityFile {context.root}/{name}-key
  UserKnownHostsFile {context.root}/{name}-known
  GlobalKnownHostsFile /dev/null
  StrictHostKeyChecking yes
  IdentitiesOnly yes
  IdentityAgent none
  BatchMode yes
  ExitOnForwardFailure yes
  ServerAliveInterval 15
  ServerAliveCountMax 3
  ConnectTimeout 10
"""
        ports = context.link["ports"]
        for start in range(0, len(ports), self.forwards_per_session):
            batch = start // self.forwards_per_session
            config_name = f"{name}-ssh-{batch}.conf"
            forwards = [
                f'  RemoteForward {address}:{context.internal(index)} {port["host"]}:{port["target"]}'
                for index, port in enumerate(
                    ports[start : start + self.forwards_per_session], start
                )
            ]
            exit["files"][config_name] = common + "\n".join(forwards) + "\n"
            exit["units"][f"{context.tag}-ssh-{batch}.service"] = service(
                f"/usr/bin/ssh -NT -F {context.root}/{config_name} tunnel"
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
        for index, port in enumerate(ports):
            entry["listeners"].append(context.internal(index))
            entry["backends"].append((port, address, context.internal(index), context.link))
