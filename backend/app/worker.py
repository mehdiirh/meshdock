"""Single-writer, lease-based reconciler with durable host receipts and compensation."""

import json
import signal
import threading
import time
from dataclasses import dataclass

from . import settings
from .artifacts import ARTIFACTS
from .db import audit, connect, initialize, log, uid
from .planner import build, empty
from .security import AppError, unseal
from .ssh import Remote

TERMINAL = {"succeeded", "failed", "superseded", "recovery_required"}


class DemoRemote:
    """Explicit simulation mode; never opens a socket or changes a remote host."""

    def __init__(self, server, credential, namespace):
        self.server = server

    def install_agent(self):
        pass

    def call(self, action, payload):
        time.sleep(0.08)
        return {"ok": True, "simulated": True}

    def close(self):
        pass


@dataclass
class Target:
    server: dict
    plan: dict

    @property
    def identity(self):
        return f'{self.server["host"]}:{self.server["ssh_port"]}'


def targets(previous, desired):
    """Retain old endpoints for cleanup when a server's address is replaced."""
    plans = build(desired)
    result = {}
    for server in previous.get("servers", []):
        target = Target(server, empty())
        target.plan.pop("backends")
        target.plan.pop("relay")
        result[target.identity] = target
    for server in desired["servers"]:
        target = Target(server, plans[server["id"]])
        result[target.identity] = target
    return list(result.values())


class Worker:
    def __init__(self, remote_factory=None):
        self.owner = uid()
        self.fence = 0
        self.remote_factory = remote_factory or (DemoRemote if settings.DEMO else Remote)
        self.stopped = threading.Event()
        self.lease_lost = threading.Event()

    def heartbeat(self):
        while not self.stopped.wait(10):
            with connect(True) as database:
                count = database.execute(
                    "UPDATE leader SET until=? WHERE id=1 AND owner=?",
                    (time.time() + settings.LEASE_SECONDS, self.owner),
                ).rowcount
                if not count:
                    self.lease_lost.set()
                    return
                database.execute(
                    "UPDATE jobs SET lease_until=? WHERE owner=? AND status='running'",
                    (time.time() + settings.LEASE_SECONDS, self.owner),
                )

    def acquire(self):
        with connect(True) as database:
            leader = database.execute("SELECT * FROM leader WHERE id=1").fetchone()
            if leader and leader["until"] > time.time() and leader["owner"] != self.owner:
                return False
            database.execute(
                "INSERT INTO leader(id,owner,until,epoch) VALUES(1,?,?,1) ON CONFLICT(id) DO UPDATE SET owner=excluded.owner,until=excluded.until,epoch=leader.epoch+1",
                (self.owner, time.time() + settings.LEASE_SECONDS),
            )
            self.fence = database.execute("SELECT epoch FROM leader WHERE id=1").fetchone()[0]
        return True

    def owns_lease(self, database):
        leader = database.execute("SELECT * FROM leader WHERE id=1").fetchone()
        return bool(
            leader
            and leader["owner"] == self.owner
            and leader["epoch"] == self.fence
            and leader["until"] > time.time()
        )

    def claim(self):
        with connect(True) as database:
            if not self.owns_lease(database):
                self.lease_lost.set()
                return None
            # An interrupted job is compensated before any newer generation can run.
            interrupted = database.execute(
                "SELECT * FROM jobs WHERE status='running' AND owner!=? ORDER BY created LIMIT 1",
                (self.owner,),
            ).fetchone()
            if interrupted:
                database.execute(
                    "UPDATE jobs SET status='recovering' WHERE id=?",
                    (interrupted["id"],),
                )
            row = database.execute(
                "SELECT * FROM jobs WHERE status='recovering' ORDER BY created LIMIT 1"
            ).fetchone()
            if not row:
                if database.execute(
                    "SELECT 1 FROM jobs WHERE status='recovery_required'"
                ).fetchone():
                    return None
                row = database.execute(
                    "SELECT * FROM jobs WHERE status IN ('queued','retrying') AND next_run<=? ORDER BY created LIMIT 1",
                    (time.time(),),
                ).fetchone()
            if not row:
                return None
            job = dict(row)
            database.execute(
                "UPDATE jobs SET status='running',owner=?,started=?,lease_until=?,attempt=attempt+1 WHERE id=?",
                (
                    self.owner,
                    time.time(),
                    time.time() + settings.LEASE_SECONDS,
                    job["id"],
                ),
            )
            job["attempt"] += 1
            return job

    def remember(self, job, receipt):
        with connect(True) as database:
            database.execute(
                "UPDATE jobs SET receipt=? WHERE id=? AND owner=?",
                (json.dumps(receipt), job["id"], self.owner),
            )

    def remote(self, server, namespace):
        with connect() as database:
            row = database.execute(
                "SELECT encrypted FROM credentials WHERE id=?",
                (server["credential_id"],),
            ).fetchone()
        if not row:
            raise AppError("not_found")
        return self.remote_factory(server, unseal(row["encrypted"]), namespace)

    def operate(self, server, namespace, action, payload, *, install=False):
        with connect() as database:
            if self.lease_lost.is_set() or not self.owns_lease(database):
                self.lease_lost.set()
                raise AppError("stale_worker")
        remote = self.remote(server, namespace)
        try:
            if install:
                remote.install_agent()
            return remote.call(action, {**payload, "fence": self.fence})
        finally:
            remote.close()

    def compensate(self, job, receipt, namespace):
        log(job["id"], "rolling_back")
        success = True
        for item in reversed(receipt.get("hosts", [])):
            try:
                self.operate(
                    item["server"],
                    namespace,
                    "rollback",
                    {"generation": receipt["generation"]},
                    install=True,
                )
                item["rolled_back"] = True
                self.remember(job, receipt)
            except Exception:
                success = False
                log(
                    job["id"],
                    "recovery_required",
                    server=item["server"]["id"],
                    level="error",
                )
        return success

    def finish(self, job, status, error=None, delay=0):
        with connect(True) as database:
            database.execute(
                "UPDATE jobs SET status=?,error_code=?,finished=?,next_run=? WHERE id=? AND owner=?",
                (
                    status,
                    error,
                    None if status == "retrying" else time.time(),
                    time.time() + delay,
                    job["id"],
                    self.owner,
                ),
            )

    def process(self, job):
        snapshot = json.loads(job["snapshot"])
        namespace = snapshot["namespace"]
        receipt = json.loads(job["receipt"])
        if job["status"] == "recovering":
            ok = self.compensate(job, receipt, namespace)
            self.finish(
                job,
                "failed" if ok else "recovery_required",
                "recovered" if ok else "recovery_required",
            )
            log(job["id"], "recovered" if ok else "recovery_required")
            return
        with connect() as database:
            previous = json.loads(
                database.execute("SELECT applied FROM state WHERE id=1").fetchone()[0]
            )
        receipt = {"generation": job["id"] + f'{job["attempt"]:04x}', "hosts": []}
        self.remember(job, receipt)
        log(job["id"], "worker_claimed", "simulation" if settings.DEMO else "")
        try:
            fleet = targets(previous, snapshot)
            for target in fleet:
                server = target.server
                log(job["id"], "preparing", server=server["id"])
                # Write intent BEFORE the network call: a lost reply is an uncertain outcome.
                receipt["hosts"].append({"server": server, "phase": "preparing"})
                self.remember(job, receipt)
                self.operate(
                    server,
                    namespace,
                    "prepare",
                    {
                        "generation": receipt["generation"],
                        "plan": target.plan,
                        "artifacts": ARTIFACTS,
                    },
                    install=True,
                )
                receipt["hosts"][-1]["phase"] = "prepared"
                self.remember(job, receipt)
            for item in receipt["hosts"]:
                log(job["id"], "applying", server=item["server"]["id"])
                self.operate(
                    item["server"],
                    namespace,
                    "apply",
                    {"generation": receipt["generation"]},
                )
                item["phase"] = "applied"
                self.remember(job, receipt)
            # Reverse transports need a short convergence window after both sides are started.
            for item in receipt["hosts"]:
                log(job["id"], "checking", server=item["server"]["id"])
                for attempt in range(12):
                    try:
                        self.operate(
                            item["server"],
                            namespace,
                            "health",
                            {"generation": receipt["generation"]},
                        )
                        break
                    except AppError as error:
                        if error.code != "health_failed" or attempt == 11:
                            raise
                        time.sleep(3)
            # Commit markers retain the previous generation, so a later host's failure remains reversible.
            for item in receipt["hosts"]:
                self.operate(
                    item["server"],
                    namespace,
                    "commit",
                    {"generation": receipt["generation"]},
                )
            with connect(True) as database:
                leader = database.execute("SELECT * FROM leader WHERE id=1").fetchone()
                if not leader or leader["owner"] != self.owner or leader["until"] <= time.time():
                    self.lease_lost.set()
                    raise RuntimeError("lease_lost")
                database.execute(
                    "UPDATE state SET applied=?,applied_revision=? WHERE id=1",
                    (job["snapshot"], job["revision"]),
                )
                database.execute(
                    "UPDATE jobs SET status='succeeded',finished=? WHERE id=? AND owner=?",
                    (time.time(), job["id"], self.owner),
                )
                audit(database, "worker", "deployment_succeeded", job["id"])
            log(job["id"], "succeeded")
        except Exception as error:
            code = error.code if isinstance(error, AppError) else "worker_error"
            details = error.details if isinstance(error, AppError) else None
            log(
                job["id"],
                code,
                detail=json.dumps(details) if details else "",
                server=details.get("server_id") if details else None,
                level="error",
            )
            recovered = self.compensate(job, receipt, namespace)
            if not recovered:
                self.finish(job, "recovery_required", code)
            elif job["attempt"] < settings.MAX_ATTEMPTS:
                self.finish(job, "retrying", code, delay=5 * 2 ** job["attempt"])
                log(job["id"], "retrying")
            else:
                self.finish(job, "failed", code)
                log(job["id"], "rolled_back")

    def run(self):
        initialize()
        while not self.stopped.is_set():
            if not self.acquire():
                self.stopped.wait(5)
                continue
            heartbeat = threading.Thread(target=self.heartbeat, daemon=True)
            heartbeat.start()
            try:
                while not self.stopped.is_set() and not self.lease_lost.is_set():
                    job = self.claim()
                    if job:
                        self.process(job)
                    else:
                        self.stopped.wait(1)
            finally:
                self.stopped.set()
                heartbeat.join(timeout=12)
                with connect(True) as database:
                    database.execute("UPDATE leader SET until=0 WHERE owner=?", (self.owner,))


def main():
    worker = Worker()
    signal.signal(signal.SIGTERM, lambda *_: worker.stopped.set())
    signal.signal(signal.SIGINT, lambda *_: worker.stopped.set())
    worker.run()


if __name__ == "__main__":
    main()
