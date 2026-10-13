# Decisions and questions for the owner

Proceeding without blocking questions, as requested.

- Linux targets: Debian/Ubuntu with systemd, root SSH, IPv4 transport addresses. Other operating systems are rejected before activation.
- Initial traffic contract: TCP forwarding. UDP and IPv6 tunnel addressing are not silently emulated; they require future adapters and capability validation.
- Entry/exit are general-purpose roles (Iran/kharej are deployment examples, never hardcoded).
- One control-plane installation owns one topology. Many entry servers can connect to many exit servers. Shared entry ports form pools; pool policy is round-robin, least-connections, or ordered failover.
- Changes queue reconciliation immediately. Workers serialize deployment generations, coalesce obsolete queued revisions, retry transient failures, and retain rollback/recovery information.
- Secrets are encrypted with a separate persistent master key. Back up the database AND key; losing the key loses access to encrypted credentials.
- Password login is for administrators; programmatic clients use revocable, scoped Bearer API keys. Browser sessions use HttpOnly cookies plus CSRF protection.
- SSH host-key discovery requires explicit fingerprint confirmation before a server can deploy. This is necessary even when a password/key is already saved.
- Shared dependency packages remain installed after cleanup. Removing shared packages automatically can break unrelated applications.
- GRE is not encrypted. Backhaul TCP is token-authenticated, not encrypted. Rathole and reverse SSH provide encrypted transports; the UI must disclose capabilities accurately.
- No existing real servers are imported or changed by development or demos.

Questions for later: preferred public domain/TLS termination; multi-tenant workspaces and non-admin roles; UDP priorities; IPv6; desired retention and alert integrations; hardware scale targets and provider firewall integration.
