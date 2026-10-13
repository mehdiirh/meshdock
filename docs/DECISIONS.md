# Decisions and questions for the owner

Proceeding without blocking questions, as requested.

- Linux targets: Debian/Ubuntu with systemd, root SSH, IPv4 transport addresses. Other operating systems are rejected before activation.
- Initial traffic contract: TCP forwarding. UDP and IPv6 tunnel addressing are not silently emulated; they require future adapters and capability validation.
- Entry/exit are general-purpose roles (Iran/kharej are deployment examples, never hardcoded).
- One control-plane installation owns one topology. Many entry servers can connect to many exit servers. Shared entry ports in socket-based connections form pools; native GRE ranges require exclusive intervals; pool policy is round-robin, least-connections, or ordered failover.
- Changes queue reconciliation immediately. Workers serialize deployment generations, coalesce obsolete queued revisions, retry transient failures, and retain rollback/recovery information.
- Secrets are encrypted with a separate persistent master key. Back up the database AND key; losing the key loses access to encrypted credentials.
- Password login is for administrators; programmatic clients use revocable, scoped Bearer API keys. Browser sessions use HttpOnly cookies plus CSRF protection.
- SSH host-key discovery requires explicit fingerprint confirmation before a server can deploy. This is necessary even when a password/key is already saved.
- Shared dependency packages remain installed after cleanup. Removing shared packages automatically can break unrelated applications.
- GRE is not encrypted. Backhaul TCP is token-authenticated, not encrypted. Rathole and reverse SSH provide encrypted transports; the UI must disclose capabilities accurately.
- No existing real servers are imported or changed by development or demos.

Questions for later: preferred public domain/TLS termination; multi-tenant workspaces and non-admin roles; UDP priorities; IPv6; desired retention and alert integrations; hardware scale targets and provider firewall integration.

- Method tuning uses adapter-owned strict Pydantic models and a generic schema-driven UI. Per-link JSON overrides are migrated and included in immutable job snapshots; rollback uses previous generation files. Supported controls are deliberately allowlisted. Transport variants that require new TLS, binding or firewall behavior need adapter work; raw configuration passthrough is not supported. Numeric bounds are controller policy, not upstream capacity claims. See METHOD-SETTINGS.md.

- Removed the former 512/64 application caps after checking upstream configurations. All adapters accept full TCP ranges subject to listener allocation, management/control conflicts, actual descriptor limits and outgoing port space. Reverse SSH splits forwards across sessions of 4,096, leaving channel headroom. This is not a throughput or universal hardware-capacity guarantee; see PORT-MAPPINGS.md for sources and tested boundaries.
- Large GRE ranges use Linux kernel forwarding. Socket adapters retain HAProxy pools. Mixed single/range GRE connections use the kernel path for every row and cannot share those public ports with another connection.
- Internal allocations belong to immutable deployment manifests, not a globally reserved public band. Existing compact JSON storage supports range intent without schema mutation; startup/migration preservation is tested.

- The owner confirmed there are no deployed installations. Use MeshDock names throughout: `MESHDOCK_*` settings, `meshdock-*` services, `/var/lib/meshdock`, `meshdock.sqlite3`, `meshdock_session`, and the `meshdock` Compose project. There are no legacy aliases or data migrations for the earlier development names. GRE interfaces use the short `md` prefix to remain within Linux's 15-byte interface-name limit.

- Transport expansion uses each pinned release's actual capabilities. Backhaul WSS clients require a verifying bridge because upstream skips certificate verification. Rathole ARM64 WS/WSS are rejected before activation because upstream ships an embedded build without WebSocket; do not advertise unsupported binary features or install an unverified substitute. Payload UDP forwarding remains outside the current TCP mapping contract.
- Deployment cancellation is cooperative and durable. Never kill an in-flight remote mutation; finish or time out, then compensate using host journals. Cancellation can require recovery after lost connectivity. Shared packages remain installed.
- Reconciliation skips unchanged server plans and restarts only units whose definitions or referenced files change. GRE/network ownership groups remain coordinated. Per-link affected IDs are persisted with new snapshots so unrelated edges do not inherit failure status. Capacity limits use stable buckets; oneshot network units keep their own small descriptor limit.
- Operational progress uses a small allowlisted JSON event protocol over the existing pinned SSH channel. Persist and stream those events, not arbitrary command stdout/stderr. Preserve safe failure categories, server identity and phase; never log tokens, private keys or raw generated configuration.

- Unfinished removals are derived from enabled applied links absent or disabled in desired state; no duplicate deployment-state table is introduced. The canvas uses a separate display projection, never silently merges retained links into saves. Retry and restore are revision-checked admin actions; both reconcile the current desired topology and the UI explicitly discloses other pending changes. Restore preserves original slot/secret material and refuses conflicting endpoint changes. An unresolved rollback is shown as uncertain.
