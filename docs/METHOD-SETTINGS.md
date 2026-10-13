# Advanced method settings

Select a connection, open **Advanced settings**, and tune that connection. The controls show defaults, units, allowed ranges, and whether the option applies to the tunnel client, server, or both. The client/server roles refer to the tunnel program, not necessarily entry/exit: Hysteria runs its client on the entry, while reverse transports run their client on the exit.

Changing a setting is a local draft until **Save & deploy**. Saving validates the whole topology and queues a revisioned deployment. Active connections may reconnect during activation. Health failure triggers coordinated rollback to the previous generation, followed by bounded retries. Unreachable hosts require recovery; this is not a distributed atomic transaction.

## Supported controls

| Method | Configurable settings | Managed behavior |
| --- | --- | --- |
| Backhaul | `transport` (`tcp`, `tcpmux`, `ws`, `wss`, `wsmux`, `wssmux`), `nodelay`, keepalive, heartbeat, channel capacity, connection pool, aggressive pooling, dial/retry timers, mux concurrency/version/frame size/receive buffer/stream buffer | Token, listener addresses, mappings and optimization policy remain managed. WSS/WSSMUX verify managed TLS; other transports are unencrypted. |
| GRE | MTU, TTL, numeric TOS | Addresses, interface names, tunnel keys, routes and forwarding remain managed. MTU is bounded to 576–1472 bytes; lower path MTUs may require a lower setting. TTL 0 inherits the inner packet TTL. |
| Rathole | Transport (`tcp`, `noise`, `tls`, `ws`, `wss`), TCP no-delay, TCP keepalive delay/interval, heartbeat interval/timeout, retry interval | Managed Noise keys or verified TLS, according to transport. |
| Reverse SSH | Server-alive interval/count, connection timeout, compression, TCP keepalive | Host verification, restricted forwarding keys and listener batching remain managed. Management sshd is untouched. |
| FRP | Transport (`tcp`, `kcp`, `quic`, `websocket`, `wss`), QUIC tuning, TCP multiplexing, mux keepalive, pool count, dial timeout, heartbeat interval/timeout | Verified managed TLS remains enabled; server pool capacity is adjusted to accommodate the client setting. |
| Hysteria 2 | Salamander on/off, stream/connection receive windows, idle timeout, keepalive, path MTU discovery | Verified TLS, credentials, UDP transport and forwarding remain managed. Initial and maximum receive windows use the configured window values. |

These are supported tuning options, not a raw configuration editor or every upstream option. Arbitrary certificate paths, raw commands and credential overrides are not exposed. Adding a transport that changes encryption, listeners, TLS handling or firewall needs requires an adapter implementation and tests, not just another dropdown value.

Mux fields appear only for mux transports. Changing Backhaul back to TCP/WS/WSS removes mux overrides from that draft. Disabling FRP mux removes its keepalive override. Each method keeps a separate draft while the inspector is open; only the selected method is saved. **Restore defaults** clears explicit overrides.

Limits are MeshDock validation bounds, not upstream throughput or hardware-capacity guarantees. Larger buffers and pools consume resources and do not automatically improve speed. Stream buffers/windows cannot exceed their parent buffer/window. Heartbeat/keepalive intervals must be shorter than their associated timeout.

## API and persistence

`GET /api/v1/methods` returns `settings_schema` for each adapter: a versioned JSON Schema with defaults, scalar types, enum choices, numeric bounds, role (`scope`), unit, conditional visibility (`when`) and cross-field `rules`. The same typed model validates the API input and generates this schema.

Each link in `PUT /api/v1/topology` accepts a `settings` object, for example:

```json
{
  "method": "backhaul",
  "settings": {
    "transport": "tcpmux",
    "mux_version": 2,
    "mux_recievebuffer": 8388608,
    "connection_pool": 16
  }
}
```

This is a link fragment; supply the other required link fields and the current topology revision. `mux_recievebuffer` intentionally matches Backhaul's spelling. API requests use the usual administrator session or administrator-scoped Bearer API key.

Only explicit overrides are stored. Omitted `settings` means `{}` (adapter defaults); topology updates replace the full desired topology. API clients changing `method` must also replace/reset incompatible settings. Unknown fields, wrong types, inactive options and invalid combinations return HTTP 422 with localized code `invalid_method_settings`; values and arbitrary unknown field names are not echoed. Rejection does not change the database revision or enqueue deployment work. Disabled links are validated too.

Alembic revision `6f3c98a12d04` adds the non-null JSON-text `links.settings` column with an empty-object default. Old queued/applied snapshots without settings compile using defaults. New snapshots include overrides; rollback restores stored generation files rather than recompiling the failed settings. Editing desired settings never resets applied-state history. Back up the database and matching encryption key before upgrading.

## Add or extend an adapter

1. Define an `Options` subclass beside the adapter, using strict `bool`, `int`, or `Literal` fields with `option(...)`. Use `scope`, `unit`, and bounds. Do not accept raw configuration strings or secrets.
2. Assign `options_model` on the adapter. Declare `when` dependencies and `lt`/`lte` rules in the model so the UI and backend share the same conditions. Conditions reference other fields' effective values.
3. Call `self.options(context.link)` during compilation. Apply values to the appropriate endpoint, retaining managed tokens/keys/addresses. Do not mutate shared adapter instances; different links may use different settings concurrently.
4. Add English/Persian field labels and a method explanation in frontend locale JSON. Backend errors remain gettext codes. No method-specific API-handler or UI-renderer branch is needed for supported scalar controls.
5. Update `frontend/e2e/fixtures/methods.json` from `/methods` metadata (public schema only). Backend tests check fixture parity. Add persistence, invalid-input, configuration-generation, deployment/rollback and real-transport tests as appropriate.
6. Preserve defaults for existing links/snapshots. A change in default behavior needs an explicit migration/versioning decision; extending this JSON object does not permit silent schema or deployment changes.

## Upstream references

Controls were checked against the pinned releases: [Backhaul 0.7.2](https://github.com/Musixal/Backhaul/blob/v0.7.2/README.md#configuration-options), [Rathole 0.5.0](https://github.com/rathole-org/rathole/blob/v0.5.0/README.md#configuration), [FRP 0.71.0 client](https://github.com/fatedier/frp/blob/v0.71.0/conf/frpc_full_example.toml) and [server](https://github.com/fatedier/frp/blob/v0.71.0/conf/frps_full_example.toml), and [Hysteria 2.13.0 client configuration](https://github.com/HyNetwork/hysteria/blob/app/v2.13.0/app/cmd/client.go). System options follow [OpenSSH client configuration](https://man.openbsd.org/ssh_config) and [Linux GRE tunnel configuration](https://man7.org/linux/man-pages/man8/ip-tunnel.8.html).

## Transport coverage and TLS

| Adapter | Selectable transports | Security and platform requirements |
| --- | --- | --- |
| Backhaul 0.7.2 | TCP, TCPMUX, WS, WSS, WSMUX, WSSMUX | WSS/WSSMUX use native server TLS and a verifying HAProxy client bridge. Other choices do not encrypt the inter-server connection. |
| Rathole 0.5.0 | TCP, Noise, TLS, WS, WSS | Noise pins its server key. TLS/WSS use owned HAProxy bridges with certificate and hostname verification. The official ARM64 binary lacks WebSocket: WS/WSS require x86_64 and fail preflight on ARM64 before activation. TCP/Noise/TLS work on both architectures. |
| FRP 0.71.0 | TCP, KCP, QUIC, WebSocket, WSS | All choices use verified TLS. WebSocket carries TLS inside WS; WSS carries WS inside TLS. KCP/QUIC need UDP and also reserve/check FRP's mandatory TCP listener on the same port. |
| Hysteria 2.13.0 | QUIC over UDP, with optional Salamander | This pinned release has no alternative underlying transport. TLS verification remains mandatory. |
| GRE / reverse SSH | GRE / SSH over TCP | These adapters have no additional selectable underlying transport. |

These choices carry **TCP application mappings**. Backhaul's separate `udp` mode forwards UDP applications; it cannot carry the TCP mappings represented by MeshDock's current API and is deliberately rejected. Payload UDP mapping is a separate capability, not interchangeable with QUIC/KCP's use of UDP for TCP transport.

MeshDock generates an encrypted-at-rest TLS identity per link, stages its certificate/key only where required, and installs trust material on the verifying endpoint. You do not need a public domain, certificate upload, or ACME setup. Private certificates do not make the tunnel indistinguishable from a public HTTPS website. There is no “skip verification” switch. The managed hostname is `tunnel.internal`; verification does not require DNS resolution of that name.

Backhaul 0.7.2's native WSS client sets `InsecureSkipVerify`; therefore MeshDock deliberately uses WS/WSMUX **only on the exit's owned loopback listener**, then performs authenticated TLS in HAProxy to the native Backhaul WSS/WSSMUX server. Rathole's TLS bridge similarly keeps plaintext on loopback. Helper listeners have per-side conflict checks and belong to the same deployment generation as their transport. Rollback restores the previous helper configuration and certificate paths too.

The `/methods` catalog now includes per-transport `encrypted`, `control_protocols`, `tls_mode`, and optional `architectures`. Allocation, preflight, firewall rules, and the UI use these capabilities. FRP QUIC exposes keepalive, idle timeout and stream limits; irrelevant TCP mux settings disappear and are rejected by the API.

Source details: [Backhaul WSS dialer](https://github.com/Musixal/Backhaul/blob/v0.7.2/internal/utils/network/ws_dialer.go), [Rathole release feature selection](https://github.com/rathole-org/rathole/blob/v0.5.0/.github/workflows/release.yml), and [FRP listener creation](https://github.com/fatedier/frp/blob/v0.71.0/server/service.go).
