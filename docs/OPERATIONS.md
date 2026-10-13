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

Management SSH must be reachable from the **controller**, directly or through a configured [SSH jump host](#ssh-jump-hosts), even when intentionally blocked from other remote servers. GRE data-plane reachability and SSH control-plane reachability are separate requirements.

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

## SSH jump hosts

When a managed server cannot accept SSH directly from the controller, configure one intermediate SSH server under **Edit server → SSH access → Via jump host**. For example:

```text
MeshDock controller → reachable entry server → restricted entry server
```

This is the management path for discovery, deployment, file transfer, health checks, cleanup and rollback. Application traffic continues to use the tunnel endpoints and method configured on the canvas.

Prepare the following:

- The controller can reach the jump host's SSH port.
- The jump host can reach the target's SSH address and port. Target hostnames are resolved by the jump host.
- The jump account can use SSH TCP forwarding to that destination (`AllowTcpForwarding`, authorized-key restrictions and `PermitOpen` must permit it). MeshDock does not modify these policies.
- Save credentials for both hosts in the SSH vault. Passwords and private keys, including passphrase-protected keys, are supported independently on each hop. The target requires root; the jump account can be an unprivileged account allowed to forward.

Select a saved directly reachable server to copy its management details, or enter a custom jump host. Verify its fingerprint independently, then continue to discover and verify the **target's** fingerprint through that path. Authentication checks each host's pinned key before sending that host's credentials. Keys are never copied to the jump server and SSH agent forwarding is not used.

A saved-server choice is a copy of its settings. Later edits or deletion of that inventory card do not change the target's saved jump configuration. Edit affected targets explicitly when rotating the jump host or its credential. Only one intermediate host is supported; chained jump hosts are rejected.

The API accepts an optional `ssh_jump` object on each server in `PUT /api/v1/topology`, and on `POST /api/v1/servers/discover`:

```json
{
  "host": "192.0.2.20",
  "ssh_port": 22,
  "ssh_jump": {
    "host": "192.0.2.10",
    "ssh_port": 22,
    "username": "operator",
    "credential_id": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "fingerprint": "SHA256:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
  }
}
```

This is a discovery request; topology server records also require the usual ID, role, transport address and target credential. Replace fixture values with verified details. Use `ssh_jump: null` for direct access. Secrets stay in the encrypted vault, while revision snapshots retain the addresses, pins and credential references needed for rollback. Referenced jump credentials cannot be deleted while needed by active inventory, deployed state or pending recovery.

Changing only the management path does not restart unchanged tunnel services. Keep the preceding jump path available until any in-flight deployment or rollback finishes; recovery uses the path saved with that operation. There is no automatic fallback to direct SSH. Errors distinguish jump connectivity, jump authentication, jump-key changes and forwarding failure.

Developer verification uses two temporary SSH servers bound only to loopback. It covers password/key authentication, host-key rejection, forwarding denial, commands and SFTP without contacting external servers:

```bash
cd backend
MESHDOCK_TEST_SSH_LOOPBACK=1 uv run python -m pytest -q tests/test_ssh_jump_loopback.py
```

## Force-delete an unavailable server

Use **Edit server → Force delete** when a machine has been permanently removed by its provider or normal deletion cannot reach it. A retained connection's removal inspector also offers force deletion for either endpoint, including a server already missing from the desired inventory.

MeshDock checks authenticated SSH access to the selected server and its connected endpoints. Each reachable endpoint receives a plan with the selected server's connections removed; other applied connections on shared servers are preserved. If the selected server is reachable, MeshDock cleans it too. If only that server is unreachable, MeshDock completes the peer cleanup and then removes its inventory record and connections, with a permanent skipped-cleanup warning.

If a peer is unreachable, including when both sides are offline, the operation pauses at **Cleanup needs attention**. Review the per-endpoint report and choose **Retry cleanup**, or explicitly confirm **Skip unreachable cleanup**. Skipping means accepting that remote tunnel services, interfaces and firewall rules may remain. A skip never means that those hosts were cleaned. SSH authentication/key-verification errors and remote command failures are not automatically treated as unreachable; fix them and retry. Command failures receive bounded automatic retries before requiring attention.

Successful cleanup remains in place while another endpoint needs attention. A remote operation failure triggers rollback on that failed endpoint only, protecting its unrelated connections; an unsuccessful rollback remains recorded as uncertain until retried. Force deletion does not roll completed peers back into a connection to a deleted machine. The worker saves endpoint progress before remote changes and resumes the same generation after a restart. This workflow intentionally differs from an ordinary coordinated deployment: it has no global cancellation/rollback button. Closing the report only closes the window; progress and actions remain available in **Deployments**.

Topology deployments are blocked until the force-delete operation completes or its remaining unavailable endpoints are explicitly skipped. Only a recovery-required job containing removal of the selected server's connections can be taken over; unrelated uncertain deployments still require recovery. Unrelated pending topology edits are not deployed by force deletion. The report and audit trail retain endpoint names and cleanup outcomes after the selected card disappears.

Skipped cleanup records retain credential references and tunnel allocation slots conservatively, preventing silent reuse of potentially live resources. Shared packages and historical recovery material remain on cleaned hosts. If a skipped host returns, clean its old MeshDock resources before reusing it; this release does not automatically revisit acknowledged skipped hosts.

Admin API calls (username/password session with CSRF, or an admin Bearer API key):

- `POST /api/v1/servers/{id}/force-delete` with `{"revision": <current revision>}` starts the durable operation and returns its job ID.
- `GET /api/v1/jobs` includes an allowlisted `force_delete` report: selected server, each endpoint's outcome, translated errors and whether skipping is available. Private manifests, secrets and receipts are never returned.
- `POST /api/v1/jobs/{id}/retry-cleanup` retries unfinished endpoints.
- `POST /api/v1/jobs/{id}/skip-cleanup` explicitly accepts the reported unreachable endpoints. Both action requests require the current revision; skipping is rejected unless every unfinished endpoint was checked and found unreachable.

The operation uses the existing versioned job snapshot and receipt fields with force-deletion metadata version 1. No database schema change or new migration is required.
