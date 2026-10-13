# Operations

## First staging deployment

Use two disposable Debian/Ubuntu systemd VMs with reachable root SSH and a simple TCP destination service. Do not import production servers for initial tests. Verify management fingerprints out of band. Confirm the provider firewall permits the chosen transport in the direction listed in its metadata.

Create one connection, verify real application traffic, then test: changing a destination; switching methods; adding a second entry and a second exit; sharing a public port; disabling/removing an edge; stopping a destination; interrupting the worker during activation; blocking SSH during rollback; restoring access and retrying recovery; restarting each VM; and cleanup. Measure throughput and latency from actual client networks separately.

The manager reserves TCP ports 20000–60999 for transport listeners and maps public application ports outside that range. Optional transport control ports can be selected outside that range, including 443 when free; listener conflicts and management SSH conflicts are rejected. TCP and UDP port spaces are validated separately. GRE uses a private /30 from 10.253.0.0/16 per link. The current implementation supports up to 500 inventory servers and 1000 link slots; it is not a benchmarked capacity guarantee. Slot reuse excludes applied and in-flight generations. Avoid overlapping private networks, multiple managers on one host, or independent firewall controllers that rewrite INPUT chains.

## Ownership

Owned resources use:

- `/var/lib/tunnel-manager/<namespace>/` for the helper, encrypted-in-transit/owner-only-on-host configuration, binaries, journals and generation files.
- `tm-<namespace>-*.service` systemd units linked to the current generation.
- GRE interfaces with the installation prefix and link slot.
- One `TM_<NAMESPACE>` INPUT chain and its jump rule. The helper never flushes global firewall tables.

No external proxy application, existing SSH configuration, default route or unrelated service is rewritten. Shared dependencies remain installed. A temporary package-start policy is removed in a finally block; after an interrupted install the next helper operation also removes its exact owned policy, preserving any pre-existing host policy. Package installation can update system packages according to the host's configured repositories; use staged hosts and maintenance windows.

## Cleanup and full removal

1. Use “Clean up tunnels” in the UI or submit `POST /api/v1/cleanup` with the current revision. Wait for the job to succeed. It disables every edge and removes active managed units, interfaces and firewall rules.
2. Recovery generations are intentionally retained. If the installation will be removed permanently, stop its worker first so it cannot reconcile while you decommission hosts.
3. On each managed host, run as root:

   ```sh
   python3 /var/lib/tunnel-manager/INSTALLATION_NAMESPACE/agent.py --uninstall INSTALLATION_NAMESPACE
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

## Local verification limitations

The bundled Compose configuration can be validated without a Docker daemon. Image builds and Linux systemd/firewall integration require a functioning daemon or staging VMs. Neither a simulated worker nor local loopback transport tests prove production kernel/firewall behavior or national-filtering reachability.
