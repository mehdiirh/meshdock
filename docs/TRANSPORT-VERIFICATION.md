# Transport and deployment verification

Verified on 2026-10-14 using synthetic credentials, TEST-NET inventories, loopback echo services and isolated Linux containers. Production tunnel deployment was not part of these tests.

- **192 backend tests passed.** Covers settings/API validation, dynamic protocol conflicts, helper allocations, secret-safe previews, all transport transitions through failure/rollback/retry, cancellation through prepare/apply/health/commit and worker recovery, migration atomicity, incremental server selection, and preserved GRE units on shared entries. The default run skips 48 opt-in network/transport cases.
- **35 real transport/TLS tests passed on Linux ARM64.** Four Rathole WS/WSS cases are excluded because the pinned upstream ARM64 binary lacks WebSocket. Actual Backhaul WSS/WSSMUX traffic passes through the same verifying HAProxy relay renderer used in deployment.
- **9 real Rathole tests passed on Linux x86_64**, including WS/WSS and rejection of untrusted/wrong-hostname TLS certificates. The official checksum-verified UPX-packed binary was decompressed in the disposable test image to run under emulation; deployed artifacts are unchanged.
- **9 isolated privileged Linux network tests passed.** GRE packets/ranges/exceptions/rollback, full-range socket capacity, outgoing-port exhaustion and reverse-SSH listener batching. No host mounts or host networking.
- **17 frontend unit tests and 9 Chrome interaction tests passed.** Transport selection and conditional validation, English/Persian, dark/light appearance, red failed edges, current-revision footer after viewing history, durable cancellation UI, and resizing the deployment panel with pointer/keyboard controls in English/Persian.
- Backend Black/Ruff, frontend Prettier/typecheck/production build and Docker Compose validation passed.

## Reproduce

```sh
cd backend
uv run python compile_locales.py
uv run python -m pytest -q
cd ../frontend
npm test
npm run build
npm run test:e2e
```

For real transport tests, provide the checksum-verified binaries for the **test machine's architecture** and HAProxy, then set `MESHDOCK_TEST_BIN_DIR` and run `tests/test_transport_smoke.py`. Keep these tests on a disposable host/container. They create local listeners only. Run both x86_64 and ARM64 to exercise upstream feature differences.

The Linux network suite uses `backend/Dockerfile.network-test` with an isolated `--privileged --network none` container; see the test module headers. Do not run those tests with host networking or mounted server directories. An opt-in test that was skipped is not evidence that the environment passed it.

## Operational limits

Cancellation waits for a remote operation to return or time out; it cannot guarantee instantaneous rollback or contact an unreachable server. Multi-server rollback remains coordinated, with durable recovery after uncertainty. Retained package installations are shared dependencies and are not uninstalled on failure.

Tests verify generated configurations, real loopback data paths and local network behavior. They do not predict connectivity, throughput or filtering conditions on an operator's actual networks. Backhaul UDP payload forwarding is outside the current TCP mapping contract. Rathole WS/WSS remain restricted to the architecture supported by the pinned release.
