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
    pass


def run(arguments, *, input=None, check=True, timeout=180):
    result = subprocess.run(
        arguments, input=input, capture_output=True, timeout=timeout
    )
    if check and result.returncode:
        # Command output may contain configuration secrets. Only stable codes leave the host.
        raise OperationError("remote_failed")
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
    def __init__(self, namespace, root=None):
        if not re.fullmatch("[a-f0-9]{10}", namespace):
            raise OperationError("preflight_failed")
        self.namespace = namespace
        self.prefix = "tm-" + namespace + "-"
        self.root = Path(root or "/var/lib/tunnel-manager/" + namespace)
        self.chain = "TM_" + namespace.upper()
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

    def preflight(self, plan):
        if os.geteuid() != 0 or not Path("/run/systemd/system").is_dir():
            raise OperationError("preflight_failed")
        if not shutil.which("apt-get"):
            raise OperationError("preflight_failed")
        previous = self.manifest(self.current())
        for name in plan["files"]:
            if not re.fullmatch("[a-zA-Z0-9_.-]+", name) or name in (
                "manifest.json",
                "journal.json",
            ):
                raise OperationError("preflight_failed")
        for name in plan["units"]:
            if not name.startswith(self.prefix) or not re.fullmatch(
                "[a-z0-9-]+\.service", name
            ):
                raise OperationError("preflight_failed")
            path = self.units / name
            if path.exists() and not (
                path.is_symlink()
                and str(path.readlink()).startswith(str(self.root) + "/current/")
            ):
                raise OperationError("ownership_conflict")
        old_interfaces = {item["name"] for item in previous["interfaces"]}
        for interface in plan["interfaces"]:
            if (
                Path("/sys/class/net", interface["name"]).exists()
                and interface["name"] not in old_interfaces
            ):
                raise OperationError("ownership_conflict")
        if shutil.which("ss"):
            listening = run(["ss", "-H", "-ltn"]).stdout.decode()
            ports = {
                int(line.split()[3].rsplit(":", 1)[1])
                for line in listening.splitlines()
            }
            if (set(plan["listeners"]) - set(previous["listeners"])) & ports:
                raise OperationError("ownership_conflict")
        if shutil.which("ss"):
            listening = run(["ss", "-H", "-lun"]).stdout.decode()
            ports = {
                int(line.split()[3].rsplit(":", 1)[1])
                for line in listening.splitlines()
            }
            if (
                set(plan.get("udp_listeners", []))
                - set(previous.get("udp_listeners", []))
            ) & ports:
                raise OperationError("ownership_conflict")
        if shutil.which("ip"):
            routes = json.loads(run(["ip", "-json", "route", "show"]).stdout)
            for interface in plan["interfaces"]:
                if any(
                    r.get("dst") == interface["network"]
                    and r.get("dev") != interface["name"]
                    for r in routes
                ):
                    raise OperationError("ownership_conflict")

    def dependencies(self, plan, artifacts):
        if not plan["units"]:
            return
        packages = [
            "haproxy",
            "iproute2",
            "iptables",
            "openssh-client",
            "openssh-server",
            "ca-certificates",
        ]
        missing = [
            p
            for p in packages
            if run(["dpkg-query", "-W", "-f=${Status}", p], check=False).stdout
            != b"install ok installed"
        ]
        if missing:
            # Do not let package post-install hooks start a competing default proxy.
            # Existing host policy is respected. The temporary policy is removed in finally.
            policy = Path("/usr/sbin/policy-rc.d")
            lock = open("/run/tunnel-manager-packages.lock", "a")
            try:
                fcntl.flock(lock, fcntl.LOCK_EX)
                created = not policy.exists() and not policy.is_symlink()
                if created:
                    fd = os.open(policy, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o755)
                    with os.fdopen(fd, "w") as stream:
                        stream.write("#!/bin/sh\nexit 101\n")
                try:
                    run(["apt-get", "update", "-qq"], timeout=240)
                    run(
                        [
                            "env",
                            "DEBIAN_FRONTEND=noninteractive",
                            "apt-get",
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
            if (
                destination.exists()
                and marker.exists()
                and marker.read_text() == expected
            ):
                continue
            with urllib.request.urlopen(url, timeout=60) as response:
                archive = response.read(100_000_001)
            if (
                len(archive) > 100_000_000
                or hashlib.sha256(archive).hexdigest() != expected
            ):
                raise OperationError("install_failed")
            if url.endswith(".zip"):
                with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
                    data = bundle.read(name)
            elif url.endswith(".tar.gz"):
                with tarfile.open(fileobj=io.BytesIO(archive)) as bundle:
                    member = next(
                        m
                        for m in bundle.getmembers()
                        if Path(m.name).name == name and m.isfile()
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

    def prepare(self, generation, plan, artifacts):
        directory = self.generation(generation)
        if (directory / "journal.json").exists():
            return
        self.preflight(plan)
        self.dependencies(plan, artifacts)
        directory.mkdir(parents=True, mode=0o700, exist_ok=True)
        for name, content in {**plan["files"], **plan["units"]}.items():
            path = directory / name
            path.write_text(content)
            path.chmod(0o600)
        if "haproxy.cfg" in plan["files"]:
            run(["haproxy", "-c", "-f", str(directory / "haproxy.cfg")])
        for name in plan["files"]:
            if name.endswith("-sshd.conf"):
                temporary = directory / (name + ".check")
                temporary.write_text(
                    plan["files"][name].replace(
                        str(self.root / "current"), str(directory)
                    )
                )
                temporary.chmod(0o600)
                try:
                    run(["/usr/sbin/sshd", "-t", "-f", str(temporary)])
                finally:
                    temporary.unlink()
        atomic_json(directory / "manifest.json", plan)
        previous = self.current()
        atomic_json(
            directory / "journal.json",
            {"previous": previous.name if previous else None, "phase": "prepared"},
        )

    def firewall(self, rules):
        exists = (
            run(["iptables", "-w", "-n", "-L", self.chain], check=False).returncode == 0
        )
        if not rules:
            if exists:
                while (
                    run(
                        ["iptables", "-w", "-C", "INPUT", "-j", self.chain], check=False
                    ).returncode
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
            if rule["protocol"] in ("tcp", "udp"):
                line += f' --dport {rule["port"]}'
            lines.append(line + " -j ACCEPT")
        lines.extend(["COMMIT", ""])
        run(["iptables-restore", "-w", "--noflush"], input="\n".join(lines).encode())
        if run(
            ["iptables", "-w", "-C", "INPUT", "-j", self.chain], check=False
        ).returncode:
            run(["iptables", "-w", "-I", "INPUT", "1", "-j", self.chain])

    def switch(self, target):
        previous = self.manifest(self.current())
        desired = self.manifest(target)
        # A full generation is activated together locally. TCP sessions may reconnect.
        for unit in previous["units"]:
            run(["systemctl", "stop", unit], check=False)
            run(["systemctl", "disable", unit], check=False)
            path = self.units / unit
            if path.is_symlink() and str(path.readlink()).startswith(
                str(self.root) + "/current/"
            ):
                path.unlink()
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
        if shutil.which("iptables"):
            self.firewall(desired["firewall"])
        run(["systemctl", "daemon-reload"])
        ordered = sorted(
            desired["units"],
            key=lambda name: (
                not name.endswith("-gre.service"),
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
                raise OperationError("health_failed") from None
        for endpoint in plan["checks"]:
            try:
                with socket.create_connection(
                    (endpoint["host"], endpoint["port"]), timeout=4
                ):
                    pass
            except OSError:
                raise OperationError("health_failed") from None

    def rollback(self, generation):
        directory = self.generation(generation)
        journal_path = directory / "journal.json"
        if not journal_path.exists():
            return
        journal = json.loads(journal_path.read_text())
        if journal["phase"] == "rolled_back":
            return
        if journal["phase"] != "prepared":
            target = (
                self.generation(journal["previous"]) if journal["previous"] else None
            )
            self.switch(target)
        journal["phase"] = "rolled_back"
        atomic_json(journal_path, journal)

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
    request = json.load(sys.stdin)
    agent = Agent(request["namespace"])
    lock = open(agent.root / "agent.lock", "a")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX)
        agent.accept_fence(request["fence"])
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
        print(json.dumps({"ok": False, "code": code}))
    finally:
        lock.close()


if __name__ == "__main__":
    main()
