# Verification record — 2026-10-13

## Completed locally

- 64 backend tests passed in the uv-managed Python 3.12 environment, including three opt-in real-binary transport tests; the Linux-only packet test was run separately and passed. Coverage includes schema upgrades with existing data, rollback of failed DDL, authentication and scopes, secret handling, revision conflicts, all six adapter plans, custom-port collisions, worker takeover/fencing, failed activation, interrupted-job recovery, cleanup, localization and multi-page event streams.
- The real transport tests verified two expanded range endpoints, an excluded middle port and explicit internal allocations using FRP 0.71.0 WSS, Hysteria 2.13.0 Salamander and Backhaul 0.7.2 using official macOS ARM64 binaries. For FRP, a Python TLS relay substitutes for the Linux HAProxy TLS listener. These tests use temporary loopback endpoints and do not connect to production servers.
- Nine frontend unit tests passed. TypeScript checking and the Vite production build passed. Black, Ruff and Prettier checks passed. The uv lock validates offline against the committed dependency declarations.
- Docker Compose configuration validated. Both services have dedicated Dockerfiles and a shared Compose definition, with a separate worker and optional Caddy HTTPS profile.
- Browser checks against the local API and simulated worker covered sign-in, a five-server/four-connection graph, switching a connection to FRP WSS with a custom port, deployment completion, persisted English/Persian events, RTL, light/dark themes, drag-and-save position persistence, automatic arrangement, and the sanitized deployment preview. Moving a node did not increment the deployment revision.
- Repository text was checked for the production hostnames, supplied VPN identity, production IP and local secret values from the surrounding task; none were found.

## Fixes found during verification

- FRP WSS needs outer TLS termination before its WebSocket listener. The owned HAProxy listener now terminates TLS and forwards to a loopback-only frps control listener. The client verifies its per-link CA and server name.
- Added an Alembic migration for optional control ports and protocol-aware collision validation.
- Fixed a GRE port variable collision and arranged GRE cleanup after failed service startup.
- Worker takeover uses durable epochs, checks lease ownership before remote actions, and recovers interrupted jobs before newer deployments.
- Recovery can reinstall the helper if initial installation failed. Orphaned temporary package policies are removed only when they exactly match this installation's policy.
- Completed event streams now drain all log pages; frontend refreshes preserve newer streamed events.
- Backend locale tests check translated error-code coverage. The method picker and graph controls use separate English/Persian catalogs.
- Reverse SSH on a custom port 22 uses OpenSSH's standard unbracketed known-host format.

## Not verified

Production image builds, Linux HAProxy/systemd integration, remote package installation, host restart and multi-host rollback still need disposable staging VMs. The Docker daemon now works. Registry/Python download DNS failures prevented building the uv-based Linux test image here; the packet test ran in a temporary cached-image container with Debian-packaged test dependencies. Its older test-only Argon2 package needed an exception-name compatibility alias to import the test harness; the GRE compiler and standalone remote helper were unchanged. Production dependencies remain managed by the committed uv lock. Browser regression tests are included in CI; local browser validation used the actual UI, while the CI Playwright suite was not executed here.

No Iran/China ISP reachability, filtering-resistance, throughput or latency measurements were performed. Transport scores in [TRANSPORTS.md](TRANSPORTS.md) are subjective engineering estimates. Private TLS certificates and packet obfuscation do not guarantee passage through restrictive networks. Follow [OPERATIONS.md](OPERATIONS.md) before production deployment.

The test runner currently emits a Starlette deprecation warning about its httpx test-client integration; all tests pass. Track the upstream transition separately from production runtime dependencies.

## Port-range verification

- All six adapter compilers accept equal-width ranges with explicit port/range exceptions. Tests cover preserved offsets, malformed inputs, overlapping exceptions/rows, management SSH, protocol-separated listeners, native-range pool conflicts, dynamic allocations, automatic/explicit control ports, migration/startup preservation, and transactional rejection of incompatible method switches.
- Live-listener tests cover loopback versus public addresses, wildcard binds, IPv6-only sockets, separate TCP/UDP spaces and refusal to trust a stale manifest as proof of ownership.
- The opt-in packet test passed on Docker Desktop ARM64, Linux `6.12.76-linuxkit`, using Debian 13 iptables-nft. Client, entry and exit ran in separate disposable network namespaces, with external networking disabled. It carried traffic through ports 1023, 30000 and 65535; excluded 20001; verified shifted range endpoints with a middle exclusion; restored a prior generation; injected a partial-rule failure; and checked idempotent cleanup, unrelated-rule preservation and restoration of interface forwarding settings.
- Actual browser checks verified saving `1023-65535` with explicit exceptions, persistence after reload, a completed simulated deployment, and rejection of a switch to Reverse SSH while retaining the draft. English/Persian and light/dark rendering were checked. CI browser regression coverage was expanded; it is separate from these local UI checks.
- Native GRE range health checks verify the inner peer and owned chain attachments, not all possible destination applications. TCP remains the supported application protocol. Socket adapter limits are application policy (512 ports, or 64 for reverse SSH), not measured upstream protocol ceilings.
