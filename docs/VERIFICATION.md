# Verification record — 2026-10-13

## Completed locally

- 31 backend tests passed, including three opt-in real-binary transport tests. Coverage includes schema upgrades with existing data, rollback of failed DDL, authentication and scopes, secret handling, revision conflicts, all six adapter plans, custom-port collisions, worker takeover/fencing, failed activation, interrupted-job recovery, cleanup, localization and multi-page event streams.
- The real transport tests carried an echo payload through FRP 0.71.0 WSS, Hysteria 2.13.0 Salamander and Backhaul 0.7.2 using official macOS ARM64 binaries. For FRP, a Python TLS relay substitutes for the Linux HAProxy TLS listener. These tests use temporary loopback endpoints and do not connect to production servers.
- Five frontend unit tests passed. TypeScript checking and the Vite production build passed. Black, Ruff and Prettier checks passed. The uv lock validates offline against the committed dependency declarations.
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

Docker image builds could not run because this Mac has no functioning Docker daemon. Linux HAProxy, systemd, iptables, GRE kernel behavior, remote package installation, host restart and multi-host rollback need disposable staging VMs. Browser regression tests are included in CI; local browser validation used the actual UI, while the CI Playwright suite was not executed here.

No Iran/China ISP reachability, filtering-resistance, throughput or latency measurements were performed. Transport scores in [TRANSPORTS.md](TRANSPORTS.md) are subjective engineering estimates. Private TLS certificates and packet obfuscation do not guarantee passage through restrictive networks. Follow [OPERATIONS.md](OPERATIONS.md) before production deployment.

The test runner currently emits a Starlette deprecation warning about its httpx test-client integration; all tests pass. Track the upstream transition separately from production runtime dependencies.
