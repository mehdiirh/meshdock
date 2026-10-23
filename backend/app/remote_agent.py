"""Standalone root helper uploaded over pinned SSH. Uses only Python's standard library.

The coordinator supplies validated plans. Every generation has a durable journal;
rollback uses the generation recorded on the host, even after a controller crash.
Only this installation's namespaced resources may be replaced or removed.
"""

import fcntl
import hashlib
import io
import json
import os
import platform
import re
import shutil
import socket
import subprocess
import sys
import tarfile
import urllib.request
import zipfile
from pathlib import Path


class OperationError(Exception):
    def __init__(self, code, detail=None):
        super().__init__(code)
        self.detail = detail or {}


def run(arguments, *, input=None, check=True, timeout=180):
    try:
        result = subprocess.run(arguments, input=input, capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise OperationError("command_timeout", {"command": Path(arguments[0]).name}) from None
    if check and result.returncode:
        # Command output may contain configuration secrets. Only stable codes leave the host.
        output = " ".join((result.stdout + result.stderr).decode(errors="replace").lower().split())
        reasons = {
            "could not get lock": "package_lock",
            "temporary failure resolving": "package_dns",
            "does not have a release file": "package_repository",
            "404 not found": "package_repository",
            "could not wait for server fd": "package_network",
            "connection timed out": "package_network",
            "no space left on device": "disk_full",
            "unable to locate package": "package_missing",
            "certificate verification failed": "package_tls",
            "certificate verification": "package_tls",
            "conflicting values set for option signed-by": "package_repository",
        }
        code = next(
            (reason for pattern, reason in reasons.items() if pattern in output), "remote_failed"
        )
        raise OperationError(
            code, {"command": Path(arguments[0]).name, "exit_code": result.returncode}
        )
    return result


def atomic_json(path, value):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value))
    temporary.chmod(0o600)
    with temporary.open("rb") as stream:
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    directory = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


class Agent:
    def __init__(self, namespace, root=None, progress=None):
        if not re.fullmatch("[a-f0-9]{10}", namespace):
            raise OperationError("preflight_failed")
        self.progress = progress or (lambda code, detail=None: None)
        self.namespace = namespace
        self.prefix = "meshdock-" + namespace + "-"
        self.root = Path(root or "/var/lib/meshdock/" + namespace)
        self.chain = "MESHDOCK_" + namespace.upper()
        self.units = Path("/etc/systemd/system")
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)

    def accept_fence(self, epoch):
        fence = self.root / "fence.json"
        previous = json.loads(fence.read_text())["epoch"] if fence.exists() else 0
        if not isinstance(epoch, int) or epoch < previous:
            raise OperationError("stale_worker")
        if epoch > previous:
            atomic_json(fence, {"epoch": epoch})

    def generation(self, generation):
        if not re.fullmatch("[a-f0-9]{32,40}", generation):
            raise OperationError("preflight_failed")
        return self.root / "generations" / generation

    def current(self):
        path = self.root / "current"
        if not path.is_symlink():
            if path.exists():
                raise OperationError("ownership_conflict")
            return None
        target = path.resolve()
        if target.parent != self.root / "generations":
            raise OperationError("ownership_conflict")
        return target

    def manifest(self, path):
        if path is None:
            return {"units": {}, "interfaces": [], "listeners": [], "firewall": []}
        return json.loads((path / "manifest.json").read_text())

    def architecture_preflight(self, plan):
        architecture = {"arm64": "aarch64", "amd64": "x86_64"}.get(
            platform.machine(), platform.machine()
        )
        for requirement in plan.get("architecture_requirements", []):
            if architecture not in requirement["supported"]:
                raise OperationError(
                    "transport_architecture_unsupported",
                    {
                        "method": requirement["method"],
                        "transport": requirement["transport"],
                        "architecture": architecture,
                    },
                )

    def preflight(self, plan):
        self.architecture_preflight(plan)
        if os.geteuid() != 0 or not Path("/run/systemd/system").is_dir():
            raise OperationError("preflight_failed")
        if not shutil.which("apt-get"):
            raise OperationError("preflight_failed")
        os_release = Path("/etc/os-release").read_text()
        if not re.search(r'^ID=["\']?(debian|ubuntu)["\']?$', os_release, re.MULTILINE):
            raise OperationError("preflight_failed")
        previous = self.manifest(self.current())
        if plan.get("public_address") and shutil.which("ip"):
            self.interface_for_address(plan["public_address"])
        if not previous["units"] and shutil.which("iptables"):
            if not run(["iptables", "-w", "-n", "-L", self.chain], check=False).returncode:
                raise OperationError("ownership_conflict")
        for name in plan["files"]:
            if not re.fullmatch("[a-zA-Z0-9_.-]+", name) or name in (
                "manifest.json",
                "journal.json",
            ):
                raise OperationError("preflight_failed")
        for name in plan["units"]:
            if not name.startswith(self.prefix) or not re.fullmatch(r"[a-z0-9-]+\.service", name):
                raise OperationError("preflight_failed")
            path = self.units / name
            if path.exists() and not (
                path.is_symlink() and str(path.readlink()).startswith(str(self.root) + "/current/")
            ):
                raise OperationError("ownership_conflict")
        old_interfaces = {item["name"] for item in previous["interfaces"]}
        for interface in plan["interfaces"]:
            if (
                Path("/sys/class/net", interface["name"]).exists()
                and interface["name"] not in old_interfaces
            ):
                raise OperationError("ownership_conflict")
        self.resource_preflight(plan)
        self.outgoing_port_preflight(plan)
        self.socket_preflight(plan)
        self.network_preflight(plan)
        if shutil.which("ip"):
            routes = json.loads(run(["ip", "-json", "route", "show"]).stdout)
            for interface in plan["interfaces"]:
                if any(
                    r.get("dst") == interface["network"] and r.get("dev") != interface["name"]
                    for r in routes
                ):
                    raise OperationError("ownership_conflict")

    def network_chains(self):
        return {
            "pre": ("nat", "PREROUTING", self.chain + "_PRE"),
            "post": ("nat", "POSTROUTING", self.chain + "_POST"),
            "input": ("nat", "INPUT", self.chain + "_IN"),
            "forward": ("filter", "FORWARD", self.chain + "_FWD"),
            "mss": ("mangle", "FORWARD", self.chain + "_MSS"),
        }

    def interface_for_address(self, address):
        interfaces = json.loads(run(["ip", "-json", "address", "show"]).stdout)
        for interface in interfaces:
            if any(item.get("local") == address for item in interface.get("addr_info", [])):
                return interface["ifname"]
        raise OperationError("public_address_missing")

    def network_preflight(self, plan):
        if not plan.get("network_interfaces"):
            return
        version = re.match(r"(\d+)\.(\d+)", platform.release())
        if plan.get("shifted_ranges") and (
            not version or tuple(map(int, version.groups())) < (4, 18)
        ):
            raise OperationError("range_kernel_unsupported")
        if shutil.which("ip"):
            for address in plan.get("forwarding_addresses", []):
                self.interface_for_address(address)
        marker = self.root / "network-state.json"
        if not marker.exists() and shutil.which("iptables"):
            for table, _, chain in self.network_chains().values():
                if not run(
                    ["iptables", "-w", "-t", table, "-n", "-L", chain], check=False
                ).returncode:
                    raise OperationError("ownership_conflict")

    def clear_udp_connections(self, peers):
        # Only original tuples on this installation's private GRE endpoints.
        # Never flush the table or match public traffic/another protocol.
        for peer in peers:
            result = run(
                [
                    "conntrack",
                    "-D",
                    "-p",
                    "udp",
                    "--orig-src",
                    peer["source"],
                    "--orig-dst",
                    peer["destination"],
                ],
                check=False,
            )
            if result.returncode and not (
                result.returncode == 1 and b"0 flow entries have been deleted" in result.stderr
            ):
                raise OperationError(
                    "remote_failed", {"command": "conntrack", "exit_code": result.returncode}
                )

    def network_down(self):
        marker = self.root / "network-state.json"
        if not marker.exists():
            return
        state = json.loads(marker.read_text())
        for table, parent, chain in self.network_chains().values():
            if run(["iptables", "-w", "-t", table, "-n", "-L", chain], check=False).returncode:
                continue
            while not run(
                ["iptables", "-w", "-t", table, "-C", parent, "-j", chain], check=False
            ).returncode:
                run(["iptables", "-w", "-t", table, "-D", parent, "-j", chain])
            run(["iptables", "-w", "-t", table, "-F", chain])
            run(["iptables", "-w", "-t", table, "-X", chain])
        boot_id = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
        if state["boot_id"] == boot_id:
            for name, previous in state["sysctls"].items():
                path = Path(name)
                # Restore only the value we set, and only during the same boot.
                if path.exists() and path.read_text().strip() == "1":
                    path.write_text(previous)
        self.clear_udp_connections(state.get("udp_conntrack_peers", []))
        marker.unlink()

    def network_up(self):
        self.network_down()
        plan = self.manifest(self.current())
        self.network_preflight(plan)
        interfaces = set(plan.get("network_interfaces", []))
        interfaces.update(
            self.interface_for_address(address) for address in plan.get("forwarding_addresses", [])
        )
        for target in plan.get("forwarding_targets", []):
            routes = json.loads(run(["ip", "-json", "route", "get", target]).stdout)
            if not routes or not routes[0].get("dev"):
                raise OperationError("preflight_failed")
            if routes[0].get("type") != "local":
                interfaces.add(routes[0]["dev"])
        sysctls = {}
        for interface in interfaces:
            if not re.fullmatch(r"[a-zA-Z0-9_.:-]{1,15}", interface):
                raise OperationError("preflight_failed")
            path = Path("/proc/sys/net/ipv4/conf") / interface / "forwarding"
            sysctls[str(path)] = path.read_text().strip()
        for interface in plan.get("loopback_interfaces", []):
            path = Path("/proc/sys/net/ipv4/conf") / interface / "route_localnet"
            sysctls[str(path)] = path.read_text().strip()
        atomic_json(
            self.root / "network-state.json",
            {
                "boot_id": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
                "sysctls": sysctls,
                "udp_conntrack_peers": plan.get("udp_conntrack_peers", []),
            },
        )
        try:
            for name in sysctls:
                Path(name).write_text("1")
            for key, (table, parent, chain) in self.network_chains().items():
                rules = plan["network_rules"].get(key, [])
                if not rules:
                    continue
                lines = ["*" + table, ":" + chain + " - [0:0]"]
                lines.extend("-A " + chain + " " + rule for rule in rules)
                lines.extend(["COMMIT", ""])
                run(["iptables-restore", "-w", "--noflush"], input="\n".join(lines).encode())
                run(["iptables", "-w", "-t", table, "-I", parent, "1", "-j", chain])
            self.clear_udp_connections(plan.get("udp_conntrack_peers", []))
        except Exception:
            self.network_down()
            raise

    def resource_preflight(self, plan):
        resources = plan.get("resources", {})
        if not resources.get("nofile"):
            return
        maximum = int(Path("/proc/sys/fs/nr_open").read_text())
        if resources["nofile"] > maximum:
            raise OperationError(
                "descriptor_capacity", {"required": resources["nofile"], "available": maximum}
            )
        allocated, unused, total = map(int, Path("/proc/sys/fs/file-nr").read_text().split())
        available = total - allocated + unused
        if resources["descriptor_budget"] > available:
            raise OperationError(
                "descriptor_capacity",
                {"required": resources["descriptor_budget"], "available": available},
            )

    @staticmethod
    def planned_sockets(plan):
        yield from plan.get("sockets", [])
        for interval in plan.get("socket_ranges", []):
            for port in range(interval["start"], interval["end"] + 1):
                yield {
                    "address": interval["address"],
                    "protocol": interval["protocol"],
                    "port": port,
                }

    def outgoing_port_preflight(self, plan):
        if not (plan.get("sockets") or plan.get("socket_ranges")) or not shutil.which("ip"):
            return
        first, last = map(int, Path("/proc/sys/net/ipv4/ip_local_port_range").read_text().split())
        # Route lookup only: no packet is sent to this documentation address.
        # A non-default/policy route can have another source; this guard detects
        # the normal Internet route, not every possible routing policy.
        result = run(["ip", "-json", "route", "get", "192.0.2.1"], check=False)
        if result.returncode:
            return
        routes = json.loads(result.stdout)
        if not routes or not routes[0].get("prefsrc"):
            return
        address = routes[0]["prefsrc"]
        # Native UDP relays and HAProxy both need automatic outgoing source
        # ports. Conservatively retain headroom for each listener protocol.
        reserved = set()
        for value in (
            Path("/proc/sys/net/ipv4/ip_local_reserved_ports").read_text().strip().split(",")
        ):
            if value:
                parts = [int(p) for p in value.split("-")]
                reserved.update(range(parts[0], parts[-1] + 1))
        occupied = {"tcp": set(), "udp": set()}
        for item in self.planned_sockets(plan):
            occupied[item["protocol"]].add(item["port"])
        for ports in occupied.values():
            if ports and all(port in ports or port in reserved for port in range(first, last + 1)):
                raise OperationError(
                    "outgoing_port_capacity", {"start": first, "end": last, "address": address}
                )

    def socket_readiness(self, plan):
        # Readiness is about every declared listener, even when target services
        # in a range have not been started yet. One ss snapshot per protocol
        # avoids thousands of network probes and their sequential timeouts.
        if not (plan.get("sockets") or plan.get("socket_ranges")):
            return
        for protocol, flag in (("tcp", "-ltn"), ("udp", "-lun")):
            required = {
                (item["address"], item["port"])
                for item in self.planned_sockets(plan)
                if item["protocol"] == protocol
            }
            if not required:
                continue
            actual = set()
            for line in run(["ss", "-H", flag]).stdout.decode().splitlines():
                fields = line.split()
                if len(fields) < 4:
                    raise OperationError(
                        "health_failed", {"check": "listener_scan", "protocol": protocol}
                    )
                try:
                    host, port = fields[3].rsplit(":", 1)
                    actual.add((host.strip("[]"), int(port)))
                except ValueError:
                    raise OperationError(
                        "health_failed", {"check": "listener_scan", "protocol": protocol}
                    ) from None
            missing = required - actual
            if missing:
                address, port = min(missing)
                raise OperationError(
                    "health_failed",
                    {
                        "check": "listener",
                        "protocol": protocol,
                        "address": address,
                        "port": port,
                        "missing": len(missing),
                    },
                )

    def socket_preflight(self, plan):
        if not shutil.which("ss"):
            return
        sockets = {}
        for item in plan.get("sockets", []):
            sockets.setdefault((item["protocol"], item["port"]), set()).add(item["address"])
        for protocol, flag in (("tcp", "-ltnpe"), ("udp", "-lunpe")):
            listening = run(["ss", "-H", flag]).stdout.decode()
            for line in listening.splitlines():
                fields = line.split()
                if len(fields) < 4:
                    raise OperationError("preflight_failed")
                address, port_text = fields[3].rsplit(":", 1)
                address = address.strip("[]").split("%", 1)[0]
                port = int(port_text)
                if address == "::" and "v6only:1" in line:
                    continue
                if address.startswith("::ffff:"):
                    address = address.removeprefix("::ffff:")
                addresses = sockets.get((protocol, port), set())
                socket_conflict = bool(addresses) and (
                    address in ("*", "0.0.0.0", "::") or address in addresses
                )
                range_conflict = any(
                    item["protocol"] == protocol
                    and item["start"] <= port <= item["end"]
                    and (address in ("*", "0.0.0.0", "::") or item["address"] == address)
                    for item in plan.get("forwarded_ranges", []) + plan.get("socket_ranges", [])
                )
                if not socket_conflict and not range_conflict:
                    continue
                # Exempt live processes only when their systemd cgroup belongs to
                # this installation. A port number in an old manifest is not proof.
                pids = re.findall(r"pid=(\d+)", line)
                owned = bool(pids)
                for pid in pids:
                    try:
                        groups = Path(f"/proc/{pid}/cgroup").read_text()
                    except OSError:
                        owned = False
                        break
                    if not any(
                        re.search(
                            r"/" + re.escape(self.prefix) + r"[a-z0-9-]+\.service(?:/|$)", group
                        )
                        for group in groups.splitlines()
                    ):
                        owned = False
                        break
                if not owned:
                    raise OperationError(
                        "listener_conflict",
                        {"protocol": protocol, "port": port, "address": address},
                    )

    @property
    def package_policy_text(self):
        return f"#!/bin/sh\n# MeshDock {self.namespace} temporary policy\nexit 101\n"

    def recover_package_policy(self, policy=None, lock_path=None):
        """Remove this helper's exact orphaned policy after an interrupted install."""
        policy = Path(policy or "/usr/sbin/policy-rc.d")
        lock_path = Path(lock_path or "/run/meshdock-packages.lock")
        with lock_path.open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            if policy.is_file() and not policy.is_symlink():
                if policy.read_text() == self.package_policy_text:
                    policy.unlink()

    def dependencies(self, plan, artifacts):
        if not plan["units"]:
            return
        packages = ["iproute2", "iptables", "ca-certificates"]
        if plan.get("udp_conntrack_peers"):
            packages.append("conntrack")
        if "haproxy.cfg" in plan["files"]:
            packages.append("haproxy")
        if any(name.endswith("-sshd.conf") for name in plan["files"]):
            packages.append("openssh-server")
        if any("/usr/bin/ssh " in unit for unit in plan["units"].values()):
            packages.append("openssh-client")
        self.progress("dependencies_checking")
        if plan.get("gre_checks"):
            packages.append("iputils-ping")
        missing = [
            p
            for p in packages
            if run(["dpkg-query", "-W", "-f=${Status}", p], check=False).stdout
            != b"install ok installed"
        ]
        if missing:
            self.progress("packages_installing", {"packages": missing})
            # Do not let package post-install hooks start a competing default proxy.
            # Existing host policy is respected. The temporary policy is removed in finally.
            policy = Path("/usr/sbin/policy-rc.d")
            lock = open("/run/meshdock-packages.lock", "a")
            try:
                fcntl.flock(lock, fcntl.LOCK_EX)
                created = not policy.exists() and not policy.is_symlink()
                if created:
                    fd = os.open(policy, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o755)
                    with os.fdopen(fd, "w") as stream:
                        stream.write(self.package_policy_text)
                try:
                    run(
                        [
                            "apt-get",
                            "-o",
                            "Acquire::ForceIPv4=true",
                            "-o",
                            "APT::Update::Error-Mode=any",
                            "update",
                            "-qq",
                        ],
                        timeout=240,
                    )
                    run(
                        [
                            "env",
                            "DEBIAN_FRONTEND=noninteractive",
                            "apt-get",
                            "-o",
                            "Acquire::ForceIPv4=true",
                            "install",
                            "-y",
                            "-qq",
                            *missing,
                        ],
                        timeout=480,
                    )
                finally:
                    if created:
                        policy.unlink()
            finally:
                lock.close()
        self.progress("dependencies_ready")
        if "openssh-server" in packages:
            Path("/run/sshd").mkdir(mode=0o755, exist_ok=True)
        for name in plan["binaries"]:
            architecture = {"arm64": "aarch64", "amd64": "x86_64"}.get(
                platform.machine(), platform.machine()
            )
            artifact = artifacts.get(name, {}).get(architecture)
            if not artifact:
                raise OperationError("preflight_failed")
            url, expected = artifact
            destination = self.root / "bin" / name
            marker = destination.with_suffix(".sha256")
            if destination.exists() and marker.exists() and marker.read_text() == expected:
                continue
            self.progress("binary_downloading", {"binary": name})
            with urllib.request.urlopen(url, timeout=60) as response:
                archive = response.read(100_000_001)
            if len(archive) > 100_000_000 or hashlib.sha256(archive).hexdigest() != expected:
                raise OperationError("install_failed")
            if url.endswith(".zip"):
                with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
                    data = bundle.read(name)
            elif url.endswith(".tar.gz"):
                with tarfile.open(fileobj=io.BytesIO(archive)) as bundle:
                    member = next(
                        m for m in bundle.getmembers() if Path(m.name).name == name and m.isfile()
                    )
                    if member.size > 100_000_000:
                        raise OperationError("install_failed")
                    data = bundle.extractfile(member).read()
            else:
                data = archive
            destination.parent.mkdir(mode=0o700, exist_ok=True)
            temporary = destination.with_suffix(".tmp")
            temporary.write_bytes(data)
            temporary.chmod(0o700)
            os.replace(temporary, destination)
            marker.write_text(expected)
            self.progress("binary_verified", {"binary": name})

    def prepare(self, generation, plan, artifacts):
        directory = self.generation(generation)
        if (directory / "journal.json").exists():
            return
        self.progress("preflight_checking")
        self.preflight(plan)
        self.progress("preflight_passed")
        self.dependencies(plan, artifacts)
        if not shutil.which("ss"):
            raise OperationError("preflight_failed")
        self.preflight(plan)
        directory.mkdir(parents=True, mode=0o700, exist_ok=True)
        for name, content in {**plan["files"], **plan["units"]}.items():
            path = directory / name
            path.write_text(content)
            path.chmod(0o600)
        self.progress("configuration_validating")
        if "haproxy.cfg" in plan["files"]:
            # Check staged certificate paths before activating the current pointer.
            temporary = directory / "haproxy.check"
            temporary.write_text(
                plan["files"]["haproxy.cfg"].replace(str(self.root / "current"), str(directory))
            )
            temporary.chmod(0o600)
            try:
                run(["haproxy", "-c", "-f", str(temporary)])
            finally:
                temporary.unlink()
        for name in plan["files"]:
            if name.endswith("-sshd.conf"):
                temporary = directory / (name + ".check")
                temporary.write_text(
                    plan["files"][name].replace(str(self.root / "current"), str(directory))
                )
                temporary.chmod(0o600)
                try:
                    run(["/usr/sbin/sshd", "-t", "-f", str(temporary)])
                finally:
                    temporary.unlink()
        atomic_json(directory / "manifest.json", plan)
        self.progress("configuration_ready")
        previous = self.current()
        atomic_json(
            directory / "journal.json",
            {"previous": previous.name if previous else None, "phase": "prepared"},
        )

    def firewall(self, rules):
        exists = run(["iptables", "-w", "-n", "-L", self.chain], check=False).returncode == 0
        if not rules:
            if exists:
                while (
                    run(["iptables", "-w", "-C", "INPUT", "-j", self.chain], check=False).returncode
                    == 0
                ):
                    run(["iptables", "-w", "-D", "INPUT", "-j", self.chain])
                run(["iptables", "-w", "-F", self.chain])
                run(["iptables", "-w", "-X", self.chain])
            return
        lines = ["*filter"]
        if not exists:
            lines.append(":" + self.chain + " - [0:0]")
        lines.append("-F " + self.chain)
        for rule in rules:
            line = f'-A {self.chain} -s {rule["source"]} -p {rule["protocol"]}'
            if rule.get("interface"):
                line += f' -i {rule["interface"]}'
            if rule.get("destination"):
                line += f' -d {rule["destination"]}'
            if rule["protocol"] in ("tcp", "udp") and "port" in rule:
                line += f' --dport {rule["port"]}'
            if rule.get("original_destination"):
                line += f' -m conntrack --ctstate DNAT --ctorigdst {rule["original_destination"]}'
            if rule.get("nonlocal"):
                line += " ! -i lo"
            lines.append(line + " -j " + rule.get("action", "ACCEPT"))
        lines.extend(["COMMIT", ""])
        run(["iptables-restore", "-w", "--noflush"], input="\n".join(lines).encode())
        if run(["iptables", "-w", "-C", "INPUT", "-j", self.chain], check=False).returncode:
            run(["iptables", "-w", "-I", "INPUT", "1", "-j", self.chain])

    def unit_signature(self, plan, unit):
        content = plan.get("units", {}).get(unit)
        if content is None:
            return None
        files = plan.get("files", {})
        pattern = re.escape(str(self.root / "current") + "/") + r"([a-zA-Z0-9_.-]+)"
        pending = re.findall(pattern, content)
        referenced = {}
        while pending:
            name = pending.pop()
            if name in referenced or name not in files:
                continue
            referenced[name] = files[name]
            pending.extend(re.findall(pattern, files[name]))
        return content, referenced

    def switch(self, target):
        previous = self.manifest(self.current())
        desired = self.manifest(target)
        network_keys = (
            "network_interfaces",
            "network_rules",
            "forwarding_addresses",
            "forwarding_targets",
            "loopback_interfaces",
            "udp_conntrack_peers",
        )
        network_changed = any(previous.get(key) != desired.get(key) for key in network_keys)
        units = previous["units"].keys() | desired["units"].keys()
        changed = {
            unit
            for unit in units
            if self.unit_signature(previous, unit) != self.unit_signature(desired, unit)
            or (network_changed and unit.endswith(("-gre.service", "-network.service")))
        }
        if any(unit.endswith("-gre.service") for unit in changed) and any(
            unit.endswith("-network.service") for unit in units
        ):
            # systemd stops a Requires= consumer when its GRE dependency stops.
            # Restart the coordinated network group even if rule text is equal.
            network_changed = True
            changed.update(
                unit for unit in units if unit.endswith(("-gre.service", "-network.service"))
            )
        if any(unit.endswith("-gre.service") for unit in changed):
            # Requires= stops the router when an overlay it binds is restarted.
            # Explicitly include it even if its config text is unchanged.
            changed.update(unit for unit in units if unit.endswith("-router.service"))
        # systemd propagates explicit stop through Requires=. Include consumers
        # transitively, including native services bound to an owned dummy address.
        while True:
            consumers = {
                unit
                for unit in units - changed
                if any(
                    dependency in changed
                    for plan in (previous, desired)
                    for line in plan["units"].get(unit, "").splitlines()
                    if line.startswith("Requires=")
                    for dependency in line.removeprefix("Requires=").split()
                )
            }
            if not consumers:
                break
            changed.update(consumers)
        # Keep unrelated running units and their network state intact. Comparing
        # referenced files also catches TLS identity changes behind a config.
        for unit in sorted(
            changed & previous["units"].keys(),
            key=lambda name: (
                not name.endswith("-router.service"),
                not name.endswith("-network.service"),
            ),
        ):
            run(["systemctl", "stop", unit])
            run(["systemctl", "disable", unit], check=False)
            path = self.units / unit
            if path.is_symlink() and str(path.readlink()).startswith(str(self.root) + "/current/"):
                path.unlink()
        # Recover partially installed rules even if the unit never became active.
        if network_changed:
            with (self.root / "network.lock").open("a") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                self.network_down()
        pointer = self.root / "current"
        if target:
            temporary = self.root / "current.next"
            temporary.unlink(missing_ok=True)
            temporary.symlink_to(target)
            os.replace(temporary, pointer)
        else:
            pointer.unlink(missing_ok=True)
        for unit in desired["units"]:
            path = self.units / unit
            if path.exists() or path.is_symlink():
                if not (
                    path.is_symlink()
                    and str(path.readlink()).startswith(str(self.root) + "/current/")
                ):
                    raise OperationError("ownership_conflict")
                path.unlink()
            path.symlink_to(self.root / "current" / unit)
        if previous["firewall"] != desired["firewall"] and shutil.which("iptables"):
            self.firewall(desired["firewall"])
        run(["systemctl", "daemon-reload"])
        ordered = sorted(
            changed & desired["units"].keys(),
            key=lambda name: (
                not name.endswith(("-gre.service", "-address.service")),
                name.endswith("-router.service"),
                name,
            ),
        )
        for unit in ordered:
            run(["systemctl", "enable", unit])
            run(["systemctl", "start", unit])

    def apply(self, generation):
        directory = self.generation(generation)
        journal = json.loads((directory / "journal.json").read_text())
        if journal["phase"] == "applied" and self.current() == directory:
            return
        self.preflight(self.manifest(directory))
        journal["phase"] = "applying"
        atomic_json(directory / "journal.json", journal)
        self.switch(directory)
        journal["phase"] = "applied"
        atomic_json(directory / "journal.json", journal)

    def health(self, generation):
        directory = self.generation(generation)
        plan = self.manifest(directory)
        for unit in plan["units"]:
            if run(["systemctl", "is-active", "--quiet", unit], check=False).returncode:
                raise OperationError("health_failed", {"check": "service", "unit": unit}) from None
        if plan.get("network_interfaces"):
            for key, (table, parent, chain) in self.network_chains().items():
                if (
                    plan["network_rules"].get(key, [])
                    and run(
                        ["iptables", "-w", "-t", table, "-C", parent, "-j", chain], check=False
                    ).returncode
                ):
                    raise OperationError(
                        "health_failed",
                        {"check": "firewall", "table": table, "parent": parent, "chain": chain},
                    )
        for check in plan.get("gre_checks", []):
            if run(
                ["ping", "-I", check["interface"], "-c", "1", "-W", "3", check["peer"]], check=False
            ).returncode:
                raise OperationError(
                    "health_failed",
                    {"check": "gre_peer", "interface": check["interface"], "peer": check["peer"]},
                )
        self.socket_readiness(plan)
        for endpoint in plan["checks"]:
            try:
                with socket.create_connection((endpoint["host"], endpoint["port"]), timeout=4):
                    pass
            except OSError:
                raise OperationError(
                    "health_failed",
                    {"check": "connection", "address": endpoint["host"], "port": endpoint["port"]},
                ) from None

    def rollback(self, generation):
        directory = self.generation(generation)
        journal_path = directory / "journal.json"
        if not journal_path.exists():
            return
        journal = json.loads(journal_path.read_text())
        if journal["phase"] == "rolled_back":
            return
        if journal["phase"] != "prepared":
            target = self.generation(journal["previous"]) if journal["previous"] else None
            self.switch(target)
        journal["phase"] = "rolled_back"
        atomic_json(journal_path, journal)

    def uninstall(self):
        if self.manifest(self.current())["units"]:
            raise OperationError("cleanup_first")
        self.switch(None)
        for suffix in ("stats.sock", "haproxy.pid"):
            Path(f"/run/meshdock-{self.namespace}-{suffix}").unlink(missing_ok=True)
        shutil.rmtree(self.root)

    def commit(self, generation):
        directory = self.generation(generation)
        journal = json.loads((directory / "journal.json").read_text())
        journal["phase"] = "committed"
        atomic_json(directory / "journal.json", journal)
        # Keep the immediately previous generation for coordinated rollback/recovery.
        keep = {generation, journal["previous"]}
        for path in directory.parent.iterdir():
            if path.name not in keep and path.is_dir() and not path.is_symlink():
                shutil.rmtree(path)


def main():
    if len(sys.argv) == 3 and sys.argv[1] in ("--network-up", "--network-down"):
        agent = Agent(sys.argv[2])
        if os.geteuid() != 0:
            raise SystemExit("Root access is required.")
        # systemctl is called while agent.lock is held; this must be a different lock.
        with (agent.root / "network.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            if sys.argv[1] == "--network-up":
                agent.network_up()
            else:
                agent.network_down()
        return
    if len(sys.argv) == 3 and sys.argv[1] == "--uninstall":
        agent = Agent(sys.argv[2])
        if os.geteuid() != 0:
            raise SystemExit("Root access is required.")
        with (agent.root / "agent.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            agent.recover_package_policy()
            agent.uninstall()
        print("Installation resources removed; shared packages were preserved.")
        return
    request = json.load(sys.stdin)
    agent = Agent(
        request["namespace"],
        progress=lambda code, detail=None: print(
            json.dumps({"event": code, "detail": detail or {}}), flush=True
        ),
    )
    lock = open(agent.root / "agent.lock", "a")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX)
        agent.accept_fence(request["fence"])
        agent.recover_package_policy()
        action = request["action"]
        generation = request["generation"]
        if action == "prepare":
            agent.prepare(generation, request["plan"], request["artifacts"])
        elif action in ("apply", "health", "rollback", "commit"):
            getattr(agent, action)(generation)
        else:
            raise OperationError("preflight_failed")
        print(json.dumps({"ok": True}))
    except Exception as error:
        code = str(error) if isinstance(error, OperationError) else "remote_failed"
        print(json.dumps({"ok": False, "code": code, "detail": getattr(error, "detail", {})}))
    finally:
        lock.close()


if __name__ == "__main__":
    main()
