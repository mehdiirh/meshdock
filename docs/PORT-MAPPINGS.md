# Port ranges and transport capabilities

Mappings describe incoming TCP and/or UDP traffic on the entry server's configured public IPv4. A port is an integer (443) or an inclusive range (`1023-65535`). The destination range must have the same width. Exceptions refer to entry ports and may themselves be ranges. They do not compress or renumber the destination range.

```json
{
  "protocol": "both",
  "public": "8000-8099",
  "target": "9000-9099",
  "host": "127.0.0.1",
  "exclude": [8001, "8050-8059"]
}
```

The `protocol` field is `tcp` (default), `udp`, or `both`, independently for each row. Reversed ranges are rejected. TCP and UDP with the same numeric port may reach different destinations. Here, entry port 8002 still maps to destination port 9002. A row must retain at least one port. Exceptions must be inside their row and must not overlap. There are at most 16 mapping rows and 128 exception entries per row.

| Adapter | Range implementation | Capacity constraint |
| --- | --- | --- |
| GRE | TCP: compact HAProxy bind ranges; UDP: compact kernel rules | TCP listeners require descriptors and outgoing ports; UDP requires conntrack capacity, not one socket per port |
| Backhaul | TCP transport: TCP and UDP; native UDP transport: UDP only; mux/WS/WSS: TCP only | Listeners, file descriptors, memory and outgoing port space |
| Rathole | Individual TCP or UDP services over TCP/Noise/TLS/WS/WSS | Listeners and persistent per-service control connections |
| FRP | Individual TCP or UDP proxies over all supported transports | Listeners and proxy resources; upstream `maxPortsPerClient=0` is unlimited |
| Hysteria 2 | Native TCP and UDP forwarding listeners | Listener resources; concurrent QUIC streams are a separate capacity |
| Reverse SSH | Config-file forwards split into sessions of at most 4,096 | OpenSSH channel capacity per session, host resources and outgoing port space |

The former 512/64 limits were conservative application policy, not upstream ceilings, and have been removed. All adapters accept the TCP port space 1–65,535 with explicit exceptions and method-aware validation. This is configuration support, **not a promise that any server can operate 65,535 listeners or that all ports can be occupied without exceptions**. All six expose TCP application mappings. GRE, Rathole, FRP and Hysteria also support UDP; Backhaul UDP support depends on its selected transport. Reverse SSH rejects UDP. A UDP outer transport alone does not imply UDP application forwarding.

For TCP `1023-65535`, socket methods need roughly 129,000 entry listeners (public plus private), while GRE needs one public entry listener and one private exit listener per mapped port (about 64,500 on each endpoint). The HAProxy configuration stays compact; the sockets are real. The compiler allocates each socket link a separate `127.77.x.y` loopback address using Linux's existing 127/8 local route. TCP-only socket links do not modify interface addresses. Links containing UDP own a `10.254.x.y/32` dummy interface on both endpoints; native listeners bind there and public UDP is DNATed to that address. Scoped INPUT guards prevent unsolicited access to private listeners. The public NIC retains its existing `route_localnet` setting. Internal ports can be reused by different links and do not consume destination services on `127.0.0.1`. Live wildcard listeners still conflict. FRP also needs a private control listener. Only available allocations are accepted.

Generated service descriptor limits scale with planned listeners/forwards and HAProxy's configured 65,536 concurrent-connection budget. Remote preflight reads `fs.nr_open` and current system-wide `file-nr` headroom before preparation and activation. It refuses a known descriptor shortage and records required/available values. The preview exposes listener count, per-process limit and an estimated descriptor budget. Estimates include headroom, not exact memory or throughput guarantees; process-level limits, cgroups, RAM, CPU and concurrent connections can still prevent startup, which invokes rollback.

A socket-bound full range can also consume every automatic outgoing source port needed by HAProxy or a native UDP relay. Preflight reads the actual `ip_local_port_range` and `ip_local_reserved_ports`, resolves a normal Internet route without sending packets, and conservatively rejects a plan occupying all that space across its listener addresses, checked separately for TCP and UDP. Linux automatic `connect()` source-port selection can run out even when listeners bind a different local IP, including the exit GRE address. Add explicit exceptions within the reported range on both endpoints; a distinct ingress IP alone is not sufficient. For example, excluding `60000-60999` leaves some outgoing capacity when that interval lies inside the server's actual ephemeral range. Required headroom depends on traffic; one available port is not a sizing recommendation. This check does not cover every policy route or guarantee capacity under load. GRE HAProxy ranges have this same constraint; binding the upstream connection to its GRE address does not free outgoing public ports for SSH, package downloads or other host traffic. No globally reserved public band is introduced or silently excluded.

Reverse SSH uses a short, pinned-key command and generated `RemoteForward` config files instead of enormous command lines. OpenSSH's documented authorized-key line limit is avoided by restricting the key and owned daemon to the link's private loopback address. Public and Unix-socket forwarding are denied. The upstream 16,384-channel ceiling is per SSH connection; batches of 4,096 listeners leave channel headroom for active traffic. This batch size is an implementation choice, not a link limit. A 64,513-port mapping uses 16 SSH sessions. Per-session traffic can still exhaust remaining channels under heavy load.

### Upstream basis

- [Backhaul v0.7.2 configuration](https://github.com/Musixal/Backhaul/blob/v0.7.2/README.md) supports port ranges and explicit local/remote mappings. We use explicit entries to retain offsets, exceptions and private bind addresses consistently.
- [Rathole v0.5.0 configuration implementation](https://github.com/rathole-org/rathole/blob/v0.5.0/src/config.rs) stores services in maps and validates each service; it does not establish the former 512-service limit.
- [FRP v0.71.0 server configuration](https://github.com/fatedier/frp/blob/v0.71.0/pkg/config/v1/server.go) defines zero `maxPortsPerClient` as unlimited. [FRP range templates](https://gofrp.org/en/docs/features/common/range/) expand into individual proxies; compact syntax does not remove listeners.
- [Hysteria v2.13.0 client implementation](https://github.com/apernet/hysteria/blob/app/v2.13.0/app/cmd/client.go) uses separate TCP-forwarding and UDP-forwarding lists. Its TPROXY/TUN modes are different architectures and are not implemented by this adapter.
- [OpenSSH 9.2 channel limit](https://github.com/openssh/openssh-portable/blob/V_9_2_P1/channels.h), [listener channel allocation](https://github.com/openssh/openssh-portable/blob/V_9_2_P1/channels.c), and [authorized key restrictions](https://github.com/openssh/openssh-portable/blob/V_9_2_P1/sshd.8). Recheck these constraints when changing supported system SSH versions.

## Conflicts and method changes

There is no universally reserved public range. Transport listeners use explicit addresses: public traffic/control listeners bind the configured public IPv4; intermediate listeners bind loopback, an owned dummy address, or a private GRE address. Port numbers can coexist on distinct addresses or different transport protocols.

Before saving, the backend checks overlapping mapping rows, management SSH, shared-pool policy, explicit control listeners, available internal allocations, and the new method's capabilities. Automatic control ports avoid mapped public ranges and other configured control ports. Internal allocations avoid destination services referenced on the same bind address. Automatic control ports can use low ports when the higher space is occupied; no global range is reserved. Allocations are deterministic plan data; each remote generation preserves its actual manifest for rollback.

Before preparing and activating a server, the helper checks live TCP/UDP listeners, including wildcard binds. An existing process is exempted only when its systemd cgroup belongs to this installation; an old manifest's port number alone is insufficient. An error records the server, address, protocol and port in deployment logs. The operator can add an explicit exception, choose a different control port, or resolve the other service. Exceptions are never silently inserted. Services appearing after the last check can still race activation; failed activation invokes the normal rollback pipeline.

Every method switch is validated in the same transaction as the topology change. An incompatible switch leaves the saved topology and job queue unchanged. The UI keeps the draft protocol, range and exceptions visible and disables saving incompatible mappings.

## GRE details

For a range such as `1023-65535 → 1023-65535`, HAProxy accepts TCP on the entry's public address and connects from its GRE address to the exit's private GRE address. The exit's HAProxy connects to the configured application host, including loopback services. No PROXY header is added, no HTTP headers or payloads are rewritten, and application TLS passes through unchanged. Applications see the exit proxy's connection rather than the original client IP.

Equal-width shifted ranges use HAProxy's signed server-port offset. Exceptions split bind ranges without renumbering destination ports. Multiple entries have separate GRE interfaces and exit listener addresses, so the same public ranges can independently reach one exit. Distinct entry ranges may reach the same target ports on different application hosts.

A GRE connection containing a range or UDP uses compact configuration for its TCP rows and kernel rules for its UDP rows. Those public intervals must be exclusive on the entry. Shared-port load balancing remains available for individual GRE ports and the other adapters. Ranges do not create per-port application health probes: the agent verifies the inner GRE peer, managed services and **every** declared listening socket. Closed destination ports may remain in a range. These checks do not establish throughput or end-user reachability.

MeshDock installs HAProxy when needed, validates staged configuration before activation, and orders its router service after the GRE interfaces. Host INPUT rules allow protocol 47 from the peer, inner ICMP for health checks, public entry listeners and private exit listeners from the entry GRE address. TCP-only GRE plans do not create NAT/FORWARD/MSS rules or change forwarding sysctls: local TCP sockets use the GRE interface MTU. UDP adds owned protocol-scoped NAT/FORWARD rules and journals forwarding changes on the relevant interfaces. Loopback UDP destinations require `route_localnet` only on the private GRE interface. UDP rules preserve offsets and exceptions; shifted UDP ranges require Linux 4.18 or later. UDP-only GRE ranges do not create HAProxy sockets. The existing destination application and default routes remain under the operator's control.

On the next reconciliation after upgrading, versioned adapter snapshots ensure existing GRE endpoints are considered for deployment even when the topology is unchanged. The remote helper removes only journaled MeshDock network rules and restores the interface values it owns before activating the proxy. It retains the previous manifest and can restore the former NAT generation after an activation/health failure. This is a coordinated rollback, not a distributed atomic transaction. Changing forwarding can interrupt active sessions, and existing NAT conntrack entries can outlive a rule change; MeshDock never flushes global conntrack state. Unmanaged services, rules and independent HAProxy installations are never adopted or removed automatically.

## Supported systems and deployment boundaries

Targets must be Debian or Ubuntu Linux with systemd and root management access. The configured public IPv4 must be assigned locally, including for the socket-based adapters. Provider NAT, IPv6, provider firewall APIs and arbitrary operating systems are outside this implementation. Protocol 47 must reach the GRE peer; ordinary public ICMP access is not required, but inner GRE ICMP must be allowed for health checks.

Range intent remains compact in the existing `links.ports` JSON column and immutable job snapshots. Alembic migration `c81f6e902a14` adds explicit TCP defaults to existing desired mappings in that JSON column; immutable jobs and applied snapshots remain unchanged. Existing integer mappings remain readable, and migration/startup preservation is tested. Older application versions cannot interpret new range records: restore a matching database/key backup when downgrading the application.

References: [HAProxy bind ranges and server-port offsets](https://docs.haproxy.org/2.8/configuration.html#4-server), [Linux IPv4 interface settings](https://www.kernel.org/doc/html/latest/networking/ip-sysctl.html), [FRP TCP proxies](https://gofrp.org/en/docs/features/tcp-udp/), [Hysteria forwarding configuration](https://v2.hysteria.network/docs/advanced/Full-Client-Config/).

## UDP readiness and verification

UDP has no universal connect/health handshake. MeshDock checks native UDP listeners, managed units and GRE peer readiness; it does not claim that every UDP destination application responds. Test with the application's actual protocol after deployment. Existing conntrack sessions may outlive a mapping change; cleanup never flushes shared conntrack state.

`test_udp.py` covers capabilities, per-row intent, protocol conflicts and migration. `test_settings_rollback.py` injects deployment health failures and verifies saved generations and retry across the UDP-capable methods. Opt-in isolated Linux tests cover real GRE TCP/UDP packets, full UDP ranges, offsets, exclusions, cleanup and restoration, and native public ingress (`test_gre_linux.py`, `test_udp_linux.py`). `test_transport_smoke.py` checks real pinned UDP tunnel binaries, including Rathole WS/WSS using x86 because the pinned ARM64 binary lacks those transports. These tests do not contact inventory servers.

Backhaul payload capabilities are verified against [its pinned transport dispatcher](https://github.com/Musixal/Backhaul/blob/v0.7.2/internal/server/server.go) and native listener implementations. Transport-specific payload metadata is published by `/api/v1/methods`; extending an adapter requires updating that contract, validation and actual packet tests.
