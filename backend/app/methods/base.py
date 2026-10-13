from dataclasses import dataclass


@dataclass(frozen=True)
class Context:
    namespace: str
    link: dict
    entry: dict
    exit: dict
    secrets: dict

    @property
    def tag(self):
        return f"tm-{self.namespace}-{self.link['slot']}"

    @property
    def root(self):
        return f"/var/lib/tunnel-manager/{self.namespace}/current"

    @property
    def control(self):
        return 20000 + self.link["slot"]

    def internal(self, index):
        return 30000 + (self.link["slot"] - 1) * 16 + index

    @property
    def filename(self):
        return f"link-{self.link['slot']}"


def service(command, description="Tunnel Manager transport", extra="", kind="simple"):
    return f"""[Unit]
Description={description}
After=network-online.target
Wants=network-online.target
[Service]
Type={kind}
ExecStart={command}
Restart={'no' if kind=='oneshot' else 'always'}
RestartSec=3
LimitNOFILE=65536
UMask=0077
{extra}
[Install]
WantedBy=multi-user.target
"""


class Adapter:
    metadata: dict

    def configure(self, context, entry, exit):
        raise NotImplementedError
