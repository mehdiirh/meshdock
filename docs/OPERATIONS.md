# Operations

## First staging deployment

Use two disposable Debian/Ubuntu systemd VMs with reachable root SSH and a simple TCP destination service. Do not import production servers for initial tests. Verify management fingerprints out of band. Confirm the provider firewall permits the chosen transport in the direction listed in its metadata.

Create one connection, verify real application traffic, then test: changing a destination; switching methods; adding a second entry and a second exit; sharing a public port; disabling/removing an edge; stopping a destination; interrupting the worker during activation; blocking SSH during rollback; restoring access and retrying recovery; restarting each VM; and cleanup. Measure throughput and latency from actual client networks separately.

Public ports have no blanket reserved band. Use integer ports or equal-width ranges with explicit entry-port exceptions. GRE ranges use kernel forwarding; other adapters expand ranges within their published application limits. Management SSH, topology overlaps, control listeners, and live server bindings are checked. TCP and UDP port spaces and bind addresses are validated separately. See [PORT-MAPPINGS.md](PORT-MAPPINGS.md) for limits, ownership, cleanup and method-switch behavior. GRE uses a private /30 from 10.253.0.0/16 per link. The current implementation supports up to 500 inventory servers and 1000 link slots; it is not a benchmarked capacity guarantee. Slot reuse excludes applied and in-flight generations. Avoid overlapping private networks, multiple managers on one host, or independent firewall controllers that rewrite INPUT chains.

## Ownership

Owned resources use:

- `/var/lib/meshdock/<namespace>/` for the helper, encrypted-in-transit/owner-only-on-host configuration, binaries, journals and generation files.
- `meshdock-<namespace>-*.service` systemd units linked to the current generation.
- GRE interfaces with the installation prefix and link slot.
- One `MESHDOCK_<NAMESPACE>` INPUT chain and its jump rule. The helper never flushes global firewall tables.

No external proxy application, existing SSH configuration, default route or unrelated service is rewritten. Shared dependencies remain installed. A temporary package-start policy is removed in a finally block; after an interrupted install the next helper operation also removes its exact owned policy, preserving any pre-existing host policy. Package installation can update system packages according to the host's configured repositories; use staged hosts and maintenance windows.

## Cleanup and full removal

1. Use “Clean up tunnels” in the UI or submit `POST /api/v1/cleanup` with the current revision. Wait for the job to succeed. It disables every edge and removes active managed units, interfaces and firewall rules.
2. Recovery generations are intentionally retained. If the installation will be removed permanently, stop its worker first so it cannot reconcile while you decommission hosts.
3. On each managed host, run as root:

   ```sh
   python3 /var/lib/meshdock/INSTALLATION_NAMESPACE/agent.py --uninstall INSTALLATION_NAMESPACE
   ```

   Replace the namespace with the value from `GET /api/v1/topology`. This command refuses while the current generation contains services; complete step 1 first. It removes the helper, generation files, private tunnel keys and binaries for this installation. It leaves shared packages and other installations alone.
4. Remove servers/credentials from the control plane as appropriate, or archive the database/key backup and remove the controller's Docker volume manually. `docker compose down` deliberately retains data.

A host that is offline cannot be cleaned up until access is restored. Do not treat a recovery-required job as successful cleanup.

## Backup and restore

Stop API and worker before a release upgrade. Use SQLite's backup API via `scripts/backup.py`, or copy the complete stopped data volume. Save the matching `master.key` separately in an encrypted backup system. A database without its original key cannot decrypt SSH credentials or tunnel secrets. Restoring a key from another installation is not recovery.

Restore database and key together, with ownership matching container UID 10001, then start the same application release. Run migrations before upgrading. Keep API and worker versions identical. Read [migration guidance](MIGRATIONS.md).

## Logs and troubleshooting

The UI stores structured per-host phase events and errors. It deliberately does not stream arbitrary command output, which can expose configuration secrets. For detailed service output use the host's journal for the exact owned unit, and redact it before sharing. Job/audit history is currently retained; monitor volume growth and back up before introducing a retention migration.

A recovery-required job blocks changes. Restore management access, confirm the host fingerprint has not changed unexpectedly, then select “Retry rollback.” Review the restored state and explicitly deploy again. Fingerprints are never auto-updated.

Management SSH must be reachable from the **controller**, even when intentionally blocked from other remote servers. GRE data-plane reachability and SSH control-plane reachability are separate requirements.

## Failed connection removal

A deletion changes the requested topology immediately, but the last applied snapshot retains the connection until a successful deployment commits. The canvas overlays those retained connections and any missing endpoint nodes. They remain visible after a reload, including after deleting a whole server or disabling a link. A failed rollback is shown as uncertain, rather than claiming that every endpoint is still deployed.

Click the connection or the unfinished-removal banner:

- **Retry removal** queues the current requested revision again. The connection stays visible while queued/running and disappears only after successful removal.
- **Restore connection** puts the applied connection and missing endpoints back into the requested topology, preserving its slot and encrypted tunnel identity. If this exactly undoes the only pending change, the worker has no remote work. Other pending changes still reconcile; the confirmation explains this.
- During an active deployment or unresolved recovery, both actions are blocked. Complete recovery in the deployment drawer first.

Restoration validates mappings and topology conflicts. If an existing endpoint's SSH identity, address, role or credential changed, restore those settings first; restoring a connection does not silently overwrite endpoint edits. Restoring one connection after a server deletion restores only that connection and its required endpoints; other removals stay pending.

`GET /api/v1/topology` includes `pending_removals` (public link plus status) and `removal_servers` (missing public endpoint records). These are display-only fields, excluded from ordinary topology PUT requests and private worker snapshots. No new database migration is needed: the projection reads the existing applied snapshot. Admin actions are `POST /api/v1/links/{id}/retry-removal` and `POST /api/v1/links/{id}/restore`, each with `{"revision": <current revision>}` and normal authentication/CSRF requirements. They enforce revision checks, recovery fencing and audit records; private tunnel material is never returned.

An installation can clean up only the resources tracked by its own database and namespace. If a new controller reports a conflict with a tunnel created by an older controller, use the original controller to finish removal. Do not erase the old database or manually remove only the interface while managed services remain.

## Local verification limitations

The bundled Compose configuration can be validated without a Docker daemon. Image builds and Linux systemd/firewall integration require a functioning daemon or staging VMs. Neither a simulated worker nor local loopback transport tests prove production kernel/firewall behavior or national-filtering reachability.

## Isolated GRE packet test

This opt-in test creates disposable client/entry/exit network namespaces, with no inventory connections. The test container needs privileges to create GRE interfaces and iptables chains, but has no host mounts and no external network at runtime:

```sh
docker build -f backend/Dockerfile.network-test -t meshdock-network-test backend
docker run --rm --privileged --network none meshdock-network-test
```

It exercises full-range boundary ports, the formerly reserved band, exceptions, shifted ranges, restoration of a previous generation, injected partial-rule failure, preservation of unrelated firewall rules, and restoration of interface forwarding settings. It complements the systemd/SSH/host-restart staging checklist above.


The same isolated image includes full-range HAProxy validators, a 4,097-forward SSH test spanning two sessions, and a Linux source-port exhaustion regression. Run them without external networking or host mounts:

```sh
docker run --rm --privileged --network none meshdock-network-test uv run --no-sync pytest -q tests/test_socket_linux.py tests/test_gre_linux.py
```

The SSH test adjusts only the disposable container's locked root test account and temporary fixture permissions. It must never run against a production host. The default skip condition requires both explicit opt-in and a container. Full-range runtime throughput/memory sizing still needs staging; a valid large configuration is not a capacity benchmark.
