from dataclasses import dataclass

from ..ports import count
from ..security import AppError


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
        return (
            self.link.get("allocated_control")
            or self.link.get("control_port")
            or 20000 + self.link["slot"]
        )

    @property
    def bind_address(self):
        return self.link.get("internal_address", "127.0.0.1")

    def internal(self, index):
        if "internal_ports" in self.link:
            return self.link["internal_ports"][index]
        return 30000 + (self.link["slot"] - 1) * 16 + index

    def auxiliary(self, index):
        return self.link.get("auxiliary_ports", [22000 + self.link["slot"]])[index]

    @property
    def filename(self):
        return f"link-{self.link['slot']}"


def service(command, description="MeshDock transport", extra="", kind="simple"):
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
    control_protocol: str | None = "tcp"

    internal_on_exit = False
    auxiliary_count = 0
    max_expanded_ports = 65535
    forwards_per_session = None
    native_ranges = False

    @property
    def mapping_capabilities(self):
        return {
            "ranges": True,
            "exceptions": True,
            "native_ranges": self.native_ranges,
            "max_ports": 65535 if self.native_ranges else self.max_expanded_ports,
            "max_listener_ports": self.max_expanded_ports,
            "capacity_basis": "kernel" if self.native_ranges else "system_resources",
            "forwards_per_session": self.forwards_per_session,
            "protocols": self.metadata["protocols"],
            "platforms": ["debian", "ubuntu"],
        }

    def internal_address(self, link):
        # Linux routes the entire 127/8 block locally. Each link gets its own
        # listener space without changing interfaces or claiming application ports.
        return f"127.77.{link['slot'] // 256}.{link['slot'] % 256}"

    def kernel_mapping(self, link):
        return False

    def validate_mappings(self, link):
        if not self.kernel_mapping(link) and count(link["ports"]) > self.max_expanded_ports:
            raise AppError(
                "mapping_limit",
                details={"limit": self.max_expanded_ports, "method": self.metadata["id"]},
            )

    def bindings(self, context, entry, exit):
        for port in context.link.get("internal_ports", []):
            entry["sockets"].append(
                {"address": context.bind_address, "port": port, "protocol": "tcp"}
            )
        for port in context.link.get("auxiliary_ports", []):
            entry["sockets"].append(
                {"address": context.bind_address, "port": port, "protocol": "tcp"}
            )
        if self.control_protocol:
            plan, server = (
                (entry, context.entry)
                if self.metadata["direction"] == "exit-to-entry"
                else (exit, context.exit)
            )
            plan["sockets"].append(
                {
                    "address": server["address"],
                    "port": context.control,
                    "protocol": self.control_protocol,
                }
            )

    def configure(self, context, entry, exit):
        raise NotImplementedError
