# Transport selection for restrictive networks

Research date: 2026-10-13. These are **engineering estimates**, not measurements of current success on any Iranian or Chinese ISP. Filtering differs by provider, time, destination reputation and direction. A nationwide shutdown, destination allowlist or blocked server IP can defeat every direct transport here. Keep independent exits and test them from the actual access network.

Scores are 1–5. The integration priority score weights TCP-only reachability 30%, resistance to simple protocol classification 25%, expected performance on loss 20%, and compatibility with reversible server-to-server forwarding 25%. These are explicitly subjective estimates. “Classification” is not a promise against active probing or traffic analysis.

| Candidate | TCP-only reachability | Classification resistance | Performance on loss | Integration fit | Weighted score | Decision |
|---|---:|---:|---:|---:|---:|---|
| FRP over WSS | 5 | 3 | 2 | 4 | 3.65 | Implemented; practical TCP alternative |
| Hysteria 2 + Salamander | 1 | 4 | 5 | 5 | 3.55 | Implemented; complementary UDP path |
| NaïveProxy | 5 | 4 | 3 | 2 | 3.60 | Next candidate; Chromium stack and proxy-to-forwarding bridge needed |
| Xray VLESS + REALITY | 5 | 4 | 3 | 2 | 3.60 | Next candidate; owned instance, target selection and proxy bridge needed |
| Chisel over HTTPS | 5 | 3 | 2 | 4 | 3.65 | Deferred: overlaps FRP WSS; requires an HTTPS deployment profile |
| AmneziaWG | 1 | 3 | 5 | 2 | 2.55 | Deferred: UDP dependence and kernel/userspace network ownership |
| Rathole Noise | 5 | 2 | 2 | 5 | 3.65 | Implemented; authenticated encryption, not web camouflage |
| Reverse SSH | 5 | 1 | 2 | 5 | 3.40 | Implemented; recognizable SSH transport |
| Backhaul TCP | 5 | 1 | 3 | 5 | 3.60 | Implemented; performance/compatibility option, no transport encryption |
| GRE | 1 | 1 | 4 | 5 | 2.60 | Implemented; protocol 47 is readily identifiable and often blocked |

Priority is portfolio-based rather than simply sorting one score: adding another ordinary TCP tunnel provides less diversity than adding both a TLS/WebSocket path and a QUIC path. No empirical censorship-resistance benchmark was performed.

## Implemented additions

**FRP WSS** uses authenticated reverse forwarding, TLS certificate validation, local-only backend listeners and a constrained allowed-port list. The installed profile uses a per-link private certificate and an automatic or operator-selected control port. It is **not browser-identical HTTPS traffic**, and a private certificate or blocked high ports can limit availability. Public-domain certificates and CDN termination need a separate reviewed profile. Port 443 is selectable when free on the receiving host; it cannot share a TCP listener with public application mappings. An owned HAProxy TLS listener forwards WebSocket upgrades over loopback to frps, whose plaintext control listener is never bound publicly. FRP documents WSS and TLS settings, including the fact that default encryption alone does not verify the server certificate. [Client configuration](https://gofrp.org/en/docs/reference/client-configures/), [TLS verification](https://gofrp.org/en/docs/features/common/network/network-tls/).

**Hysteria 2** forwards TCP application streams over QUIC/UDP, authenticates the peer using a pinned private CA, and enables Salamander packet obfuscation. It needs UDP between entry and exit. Salamander scrambles packets; it does not make UDP work when UDP is entirely blocked, nor does it turn the flow into normal HTTP/3. The profile leaves bandwidth unspecified rather than inventing an aggressive rate. No TUN device or default-route changes are used. [Client configuration](https://v2.hysteria.network/docs/advanced/Full-Client-Config/), [server configuration](https://v2.hysteria.network/docs/advanced/Full-Server-Config/).

## Other candidates researched

NaïveProxy uses Chromium's networking stack and is a promising candidate where browser-like behavior matters. It is a forward proxy rather than a drop-in reverse port-forwarder; a managed forwarding bridge and certificate/domain onboarding are needed. [Official repository](https://github.com/klzgrad/naiveproxy).

REALITY is designed as a transport-security layer and requires careful server/client configuration. A future adapter must own an isolated Xray service; it must never rewrite an existing application's routing rules. [Official configuration](https://github.com/XTLS/Xray-docs-next/blob/main/docs/en/config/transports/reality.md).

Chisel offers authenticated reverse forwarding over HTTP/WebSockets with optional verified TLS. It would be a reasonable second HTTPS implementation after public certificate management exists. [Official repository](https://github.com/jpillora/chisel).

AmneziaWG modifies WireGuard traffic characteristics but still relies on UDP. Its network interface and routing lifecycle warrants a dedicated ownership model. [Official documentation](https://docs.amnezia.org/documentation/amnezia-wg/).

## Operational boundaries

All current adapters expose **TCP application mappings**, even if their underlying transport uses UDP. IPv4 is required. Existing destination services must already be running. Provider-level firewalls and upstream allowlists are outside the controller. Switching methods can disconnect active sessions. New connections use health-checked HAProxy pools; failover cannot migrate an already established TCP session.

Per-link TLS identities last ten years and are private to the installation. They authenticate peers without disabling verification; they are not public web certificates. Recreating the connection rotates its identity. Review validity and rotate before expiration. Never export secrets in topology previews or logs.

## Verification performed

Three actual, checksum-verified transport binaries carried a TCP echo payload over loopback on macOS: FRP 0.71.0, Hysteria 2.13.0 and Backhaul 0.7.2. The FRP smoke test uses a standard-library TLS relay in place of Linux HAProxy. Generated HAProxy plans are validated on the destination during preparation; actual Linux HAProxy/systemd/firewall integration still requires staging. These tests validate protocol configuration, not filtering resistance or real-world speed.

The adapters use the pinned versions in `backend/app/artifacts.py`. Upstream documentation may describe newer features, including experimental Hysteria modes; those are not implicitly enabled by this implementation.
