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

- Removed the former 512/64 application caps after checking upstream configurations. All adapters accept full TCP ranges subject to listener allocation, management/control conflicts, actual descriptor limits and outgoing port space. Reverse SSH splits forwards across sessions of 4,096, leaving channel headroom. This is not a throughput or universal hardware-capacity guarantee; see PORT-MAPPINGS.md for sources and tested boundaries.
- Large GRE ranges use Linux kernel forwarding. Socket adapters retain HAProxy pools. Mixed single/range GRE connections use the kernel path for every row and cannot share those public ports with another connection.
- Internal allocations belong to immutable deployment manifests, not a globally reserved public band. Existing compact JSON storage supports range intent without schema mutation; startup/migration preservation is tested.
