# Verification record — 2026-10-13

## Advanced settings verification (latest)

- All six adapters expose strict, versioned settings schemas, consumed by the generic English/Persian UI. Tests cover persisted overrides, unknown/unsafe keys, strict types, conditional controls, cross-field validation, method switching, and unchanged revisions/jobs on rejection.
- 132 default backend tests passed. Optional transport/Linux tests are run separately below. Alembic tests cover upgrading existing rows, repeated startup, model/schema parity, and failure after the settings DDL reverting both the column and revision.
- Six generation-level deployment tests use real temporary files and host journals with simulated host commands: apply defaults, deploy custom settings, inject a health failure, compare every restored configuration file with the prior generation, then retry successfully. Actual multi-host systemd rollback still needs staging VMs.
- Eight real macOS loopback cases passed: FRP WSS with default and disabled mux/pool overrides; Hysteria with default and custom buffers/disabled obfuscation; Backhaul TCP, TCP mux, WebSocket, and WebSocket mux with custom buffers. FRP uses a local TLS relay in place of HAProxy in these macOS tests.
- One additional Rathole 0.5.0 Noise loopback case passed with custom TCP/heartbeat settings. Its pinned Linux ARM64 artifact was SHA-256 verified during a temporary image build; the traffic test ran with `--network none`.
- Nine tests passed in the stock uv-based Linux test image with `--privileged --network none`, no host mounts and disposable namespaces. They cover GRE packet forwarding, exclusions, MTU/TTL changes and restoration, full-range HAProxy configuration for socket methods, 4,097 SSH listeners carrying traffic with custom SSH tuning, and outgoing source-port exhaustion. The test uses the active Python interpreter rather than assuming `/usr/bin/python3`.
- Fourteen frontend unit tests and five Playwright browser tests passed using installed Chrome, isolated API mocks and a separate test server. Checks cover saved advanced settings, invalid-value blocking, per-method drafts, defaults, conditional mux controls, Persian RTL, theme switching and existing range behavior. The new panel was visually reviewed in English and Persian.
- Black, Ruff, Prettier and TypeScript/Vite builds pass. No real inventory server was contacted or changed. Numeric bounds and supported controls are documented in [METHOD-SETTINGS.md](METHOD-SETTINGS.md).

The older verification entries below describe earlier stages. Their Python-download/Linux-image and unexecuted Playwright limitations were resolved for this verification run. Full remote package/systemd staging and ISP performance measurements remain outstanding.

## Completed locally

- 69 backend tests passed in the uv-managed Python 3.12 environment, including three opt-in real-binary transport tests; eight Linux-only tests were run separately and passed. Coverage includes schema upgrades with existing data, rollback of failed DDL, authentication and scopes, secret handling, revision conflicts, all six adapter plans, custom-port collisions, worker takeover/fencing, failed activation, interrupted-job recovery, cleanup, localization and multi-page event streams.
- The real transport tests verified two expanded range endpoints, an excluded middle port and explicit internal allocations using FRP 0.71.0 WSS, Hysteria 2.13.0 Salamander and Backhaul 0.7.2 using official macOS ARM64 binaries. For FRP, a Python TLS relay substitutes for the Linux HAProxy TLS listener. These tests use temporary loopback endpoints and do not connect to production servers.
- Ten frontend unit tests passed. TypeScript checking and the Vite production build passed. Black, Ruff and Prettier checks passed. The uv lock validates offline against the committed dependency declarations.
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

Production image builds, full systemd integration, remote package installation, host restart and multi-host rollback still need disposable staging VMs. Linux HAProxy config validation and a real SSH/HAProxy forwarding path were tested in a disposable container. The Docker daemon now works. Registry/Python download DNS failures prevented building the uv-based Linux test image here; the Linux tests ran in a temporary cached-image container with Debian-packaged test dependencies. Its older test-only Argon2 package needed an exception-name compatibility alias to import the test harness; the GRE compiler and standalone remote helper were unchanged. Production dependencies remain managed by the committed uv lock. Browser regression tests are included in CI; local browser validation used the actual UI, while the CI Playwright suite was not executed here.

No Iran/China ISP reachability, filtering-resistance, throughput or latency measurements were performed. Transport scores in [TRANSPORTS.md](TRANSPORTS.md) are subjective engineering estimates. Private TLS certificates and packet obfuscation do not guarantee passage through restrictive networks. Follow [OPERATIONS.md](OPERATIONS.md) before production deployment.

The test runner currently emits a Starlette deprecation warning about its httpx test-client integration; all tests pass. Track the upstream transition separately from production runtime dependencies.

## Port-range verification

- All six adapter compilers accept equal-width ranges with explicit port/range exceptions. Tests cover preserved offsets, malformed inputs, overlapping exceptions/rows, management SSH, protocol-separated listeners, native-range pool conflicts, dynamic allocations, automatic/explicit control ports, migration/startup preservation, and transactional rejection of incompatible method switches.
- Live-listener tests cover loopback versus public addresses, wildcard binds, IPv6-only sockets, separate TCP/UDP spaces and refusal to trust a stale manifest as proof of ownership.
- The opt-in packet test passed on Docker Desktop ARM64, Linux `6.12.76-linuxkit`, using Debian 13 iptables-nft. Client, entry and exit ran in separate disposable network namespaces, with external networking disabled. It carried traffic through ports 1023, 30000 and 65535; excluded 20001; verified shifted range endpoints with a middle exclusion; restored a prior generation; injected a partial-rule failure; and checked idempotent cleanup, unrelated-rule preservation and restoration of interface forwarding settings.
- Actual browser checks verified saving `1023-65535` with explicit exceptions, persistence after reload, a completed simulated deployment, and full-range switches among all five socket methods while retaining exceptions. English/Persian and light/dark rendering were checked. CI browser regression coverage was expanded; it is separate from these local UI checks.
- Native GRE range health checks verify the inner peer and owned chain attachments, not all possible destination applications. TCP remains the supported application protocol. The former 512/64 application caps have been removed; actual allocation and remote capacity checks replace them.


## Capability-based capacity follow-up

- Full `1023-65535` compilation and method switching passed for all six adapters. The suite also tests two full-range socket links on one entry with independent loopback address spaces, control allocation below the mapped interval, preserved exclusions, descriptor shortages and actual outgoing-port range checks. The full regression result was 69 passed, with eight Linux-only tests skipped on macOS and then passed separately on Linux.
- Five actual HAProxy configuration checks passed on generated full-range socket plans, including WSS TLS and SSH health tracking. A separate Linux test activated 4,097 private SSH forwards plus their 4,097 public HAProxy listeners, then carried echo traffic through the first and second SSH sessions. A forwarding request on an unauthorized public bind address was rejected. Intermediate destination services were deliberately absent. A 4,096-line generated client config also passed the local OpenSSH parser.
- Linux source-port exhaustion was reproduced in a disposable network namespace with a four-port ephemeral range: occupying all four blocked an outgoing connection with `EADDRNOTAVAIL`; freeing one restored connectivity. The app guard uses the host's live range and reserved-port configuration, rather than hardcoding that test range or Linux defaults.
- Eight isolated Linux tests passed using Debian-packaged HAProxy 3.0.11 and OpenSSH 10.0p2 in the local Docker test harness. Five were full-range syntax checks, one exercised SSH traffic and its address restriction, one exercised outgoing-port exhaustion, and one rechecked GRE packet forwarding/rollback. These are not full 65K-listener throughput tests of every upstream binary, nor end-to-end systemd provisioning tests.
- The UI accepted the saved 64,509-port range on Backhaul, Rathole, FRP, Hysteria and reverse SSH. SSH displayed 16 sessions. English/dark and Persian/light layouts were checked; topology revision remained unchanged during these draft-only checks. The deployment preview compacts long port lists and exposes planned resource counts. Ten frontend unit tests and the production build passed. CI browser fixtures now expect capability-based method switching.
- Mapping storage is unchanged: no schema/DDL migration was necessary. Generated addresses, session groups and resource budgets are derived plan data in immutable generation manifests.

## MeshDock rename — 2026-10-13

- Renamed UI branding in both locale catalogs, login/dashboard labels, browser title, API title, backend/frontend package metadata and lockfiles, image tags, CI examples, setup/backup/dev scripts, and project documentation.
- Initially retained installation identifiers during the display-name change. The subsequent fresh-project rename below supersedes that decision.
- Backend: 77 passed, 11 opt-in transport/Linux tests skipped. Black and Ruff passed.
- Frontend: 10 unit tests passed; TypeScript/Vite production build and Prettier passed.
- All 3 browser tests passed using installed Chrome in an isolated profile. The default Playwright browser was missing and its download returned a regional HTTP 403; a temporary configuration selected Chrome without changing the committed CI browser configuration.
- Browser checks also verified MeshDock on the login screen and dashboard, English/dark and Persian/light layouts, and browser title. Refreshed documentation screenshots with mocked TEST-NET fixtures; no live server data was used.
- `uv lock --check --offline`, Docker Compose configuration validation, shell syntax and Git whitespace checks passed. No production hosts were contacted or modified.

## Fresh-project naming and public documentation — 2026-10-13

The owner confirmed that there are no deployed installations. Configuration, cookies, API-key prefixes, browser storage, managed units, firewall chains, runtime paths, database filename, Docker project/volume names, and the container account now use MeshDock names, with no compatibility aliases. GRE interfaces use `md` to stay within Linux's 15-byte limit. Schema definitions and Alembic history are unchanged.

- The final backend suite passed 78 tests, including the maximum-slot interface/chain-length check and API-key display-prefix check. Eleven platform/real-binary tests were skipped in the macOS suite.
- Eight Linux network tests passed in a disposable privileged container with external networking disabled and no host mounts. These covered renamed GRE/firewall resources, packet forwarding, rollback/cleanup, full-range HAProxy validation, reverse-SSH forwarding and outgoing-port exhaustion.
- The stock test-image build could not retrieve the pinned uv package from its package index. Linux tests used the existing offline test image plus current application/test sources and distro Python/pytest, with `--noconftest`. Its older Argon2 exception was aliased to the equivalent current name in the test process only; no application source was altered for this workaround. These results do not validate building the stock Docker images.
- Ten frontend unit tests, TypeScript/Vite production build, and all three browser regressions passed. Browser tests used installed Chrome in an isolated profile. Black, Ruff, Prettier, shell syntax, and Compose configuration validation passed.
- The gallery contains five actual UI captures made with fictional fixtures and RFC 5737 addresses: dark, light, Persian RTL, GRE ranges and socket capacity. The reproducible capture script checks branding, node count, language/theme state, mapping count and capacity guidance; it rejects unexpected requests and never contacts the backend or managed hosts.
- All 33 local README/gallery links and section anchors resolve. Screenshots were inspected for readability and public-safe data. No production host was contacted or changed.

## Optional SSH jump hosts — 2026-10-14

- The full backend suite passed 229 tests with 53 opt-in/platform tests skipped. A subsequent cleanup regression was added; all 21 focused jump-host tests passed. Coverage includes strict API validation, encrypted credential resolution/retention, host-key verification before authentication, safe error reporting, deployment/rollback through saved access paths and unchanged data-plane plans.
- Five opt-in integration tests passed against two temporary SSH servers bound to loopback, using generated fixture keys and temporary files. They exercised password and public-key authentication, target discovery through the jump, SSH commands, SFTP, both host-key mismatches and denied forwarding. The final run treated unhandled test-server thread exceptions as failures. No external SSH server was contacted.
- Migration tests upgraded existing data from `92bfc04e31ad`, injected and rolled back a failed upgrade, repeated successful startup and checked SQLAlchemy/Alembic schema agreement.
- All 14 browser regressions passed with mocked APIs and installed Chrome. The two jump-host workflows passed again after correcting HTML username-pattern validation. Tests verify saved-server reuse, explicit custom-key trust, target rediscovery through the selected route, invalid usernames, and returning to direct access. An actual UI screenshot was inspected.
- All 19 frontend unit tests, TypeScript/Vite build, Black, Ruff, Prettier, Git whitespace checks and Docker Compose configuration validation passed. The existing Starlette/httpx deprecation warning remains.
- Production controller images and server configuration were not changed. Reachability and SSH forwarding policy between any real controller, jump host and target still require deployment-specific verification.

## Force deletion of unavailable servers — 2026-10-14

- The full backend suite passed 247 tests, with 53 opt-in/platform tests skipped. Seventeen focused tests cover missing destinations, both endpoints offline, explicit skip, per-endpoint cleanup, prepare/apply/health/commit failures, rollback on the failed endpoint, bounded retries, uncertain rollback, worker restart, lease loss, related recovery takeover, rejection of unrelated recovery, preserved shared tunnels, slot retention, credential protection, redaction, admin scope and revision checks.
- All 16 browser regressions passed before adding the reload/Persian case; the final three force-deletion browser tests then passed together. They use mocked APIs and installed Chrome, never real hosts. They verify acknowledgement before starting, cleaned versus skipped endpoints, a second confirmation for skipping unreachable peers, persisted attention after reload and Persian RTL rendering. The actual cleanup-report screenshot was inspected.
- Nineteen frontend unit tests, the TypeScript/Vite production build, Black, Ruff, Prettier, Git whitespace checks and Docker Compose configuration validation passed. The existing Starlette/httpx test-client deprecation warning remains.
- No new schema fields were introduced: existing Alembic-managed jobs store version-1 force-deletion metadata and durable receipts. Existing migration regression tests remain green. Native tunnel adapters and packet rules were not changed in this feature.
- Feature testing used isolated data and simulated managed hosts. This implementation was not deployed to a production MeshDock controller. Real-world SSH reachability and upstream/provider deletion behavior remain environment-dependent.
