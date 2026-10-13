# Port ranges and transport capabilities

Mappings describe incoming TCP traffic on the entry server's configured public IPv4. A port is an integer (443) or an inclusive range (`1023-65535`). The destination range must have the same width. Exceptions refer to entry ports and may themselves be ranges. They do not compress or renumber the destination range.

```json
{
  "public": "8000-8099",
  "target": "9000-9099",
  "host": "127.0.0.1",
  "exclude": [8001, "8050-8059"]
}
```

Here, entry port 8002 still maps to destination port 9002. A row must retain at least one port. Exceptions must be inside their row and must not overlap. There are at most 16 mapping rows and 128 exception entries per row.

| Adapter | Range implementation | Capacity constraint |
| --- | --- | --- |
| GRE | Compact kernel DNAT/SNAT rules split around exceptions | Port space and actual conflicts; no listener per forwarded port |
| Backhaul TCP | Explicit server mappings with preserved offsets | Listeners, file descriptors, memory and outgoing port space |
| Rathole Noise | Individual service definitions | Listeners and persistent per-service control connections |
| FRP WSS | Individual TCP proxies with allowed internal ports | Listeners and proxy resources; upstream `maxPortsPerClient=0` is unlimited |
| Hysteria 2 | TCP forwarding listeners over UDP transport | Listener resources; concurrent QUIC streams are a separate capacity |
| Reverse SSH | Config-file forwards split into sessions of at most 4,096 | OpenSSH channel capacity per session, host resources and outgoing port space |

The former 512/64 limits were conservative application policy, not upstream ceilings, and have been removed. All adapters accept the TCP port space 1–65,535 with explicit exceptions and method-aware validation. This is configuration support, **not a promise that any server can operate 65,535 listeners or that all ports can be occupied without exceptions**. All six expose TCP application mappings; a UDP transport does not imply UDP application forwarding.

For `1023-65535`, socket methods need roughly 129,000 entry listeners (public plus private), while GRE uses compact kernel rules. The compiler allocates each socket link a separate `127.77.x.y` loopback address using Linux's existing 127/8 local route. It does not modify interface addresses. Internal ports can be reused by different links and do not consume destination services on `127.0.0.1`. Live wildcard listeners still conflict. FRP also needs a private control listener. Only available allocations are accepted.

Generated service descriptor limits scale with planned listeners/forwards and HAProxy's configured 65,536 concurrent-connection budget. Remote preflight reads `fs.nr_open` and current system-wide `file-nr` headroom before preparation and activation. It refuses a known descriptor shortage and records required/available values. The preview exposes listener count, per-process limit and an estimated descriptor budget. Estimates include headroom, not exact memory or throughput guarantees; process-level limits, cgroups, RAM, CPU and concurrent connections can still prevent startup, which invokes rollback.

A socket-bound full range can also consume every automatic outgoing TCP source port on the entry's egress IP. Preflight reads the actual `ip_local_port_range` and `ip_local_reserved_ports`, resolves a normal Internet route without sending packets, and rejects a plan occupying all that space. Add explicit exceptions within the reported range or use a distinct ingress IP. For example, excluding `60000-60999` leaves some outgoing capacity when that interval lies inside the server's actual ephemeral range. Required headroom depends on traffic; one available port is not a sizing recommendation. This check does not cover every policy route or guarantee capacity under load. Native GRE does not bind a socket for each forwarded public port and does not have this particular listener constraint. No globally reserved public band is introduced or silently excluded.

Reverse SSH uses a short, pinned-key command and generated `RemoteForward` config files instead of enormous command lines. OpenSSH's documented authorized-key line limit is avoided by restricting the key and owned daemon to the link's private loopback address. Public and Unix-socket forwarding are denied. The upstream 16,384-channel ceiling is per SSH connection; batches of 4,096 listeners leave channel headroom for active traffic. This batch size is an implementation choice, not a link limit. A 64,513-port mapping uses 16 SSH sessions. Per-session traffic can still exhaust remaining channels under heavy load.

### Upstream basis

- [Backhaul v0.7.2 configuration](https://github.com/Musixal/Backhaul/blob/v0.7.2/README.md) supports port ranges and explicit local/remote mappings. We use explicit entries to retain offsets, exceptions and private bind addresses consistently.
- [Rathole v0.5.0 configuration implementation](https://github.com/rathole-org/rathole/blob/v0.5.0/src/config.rs) stores services in maps and validates each service; it does not establish the former 512-service limit.
- [FRP v0.71.0 server configuration](https://github.com/fatedier/frp/blob/v0.71.0/pkg/config/v1/server.go) defines zero `maxPortsPerClient` as unlimited. [FRP range templates](https://gofrp.org/en/docs/features/common/range/) expand into individual proxies; compact syntax does not remove listeners.
- [Hysteria v2.13.0 client implementation](https://github.com/apernet/hysteria/blob/app/v2.13.0/app/cmd/client.go) uses a list of TCP-forwarding entries. Its TPROXY/TUN modes are different architectures and are not implemented by this adapter.
- [OpenSSH 9.2 channel limit](https://github.com/openssh/openssh-portable/blob/V_9_2_P1/channels.h), [listener channel allocation](https://github.com/openssh/openssh-portable/blob/V_9_2_P1/channels.c), and [authorized key restrictions](https://github.com/openssh/openssh-portable/blob/V_9_2_P1/sshd.8). Recheck these constraints when changing supported system SSH versions.

## Conflicts and method changes

There is no universally reserved public range. Transport listeners use explicit addresses: public traffic/control listeners bind the configured public IPv4; intermediate listeners bind loopback or a private GRE address. Port numbers can coexist on distinct addresses or different transport protocols.

Before saving, the backend checks overlapping mapping rows, management SSH, shared-pool policy, explicit control listeners, available internal allocations, and the new method's capabilities. Automatic control ports avoid mapped public ranges and other configured control ports. Internal allocations avoid destination services referenced on the same bind address. Automatic control ports can use low ports when the higher space is occupied; no global range is reserved. Allocations are deterministic plan data; each remote generation preserves its actual manifest for rollback.

Before preparing and activating a server, the helper checks live TCP/UDP listeners, including wildcard binds. An existing process is exempted only when its systemd cgroup belongs to this installation; an old manifest's port number alone is insufficient. An error records the server, address, protocol and port in deployment logs. The operator can add an explicit exception, choose a different control port, or resolve the other service. Exceptions are never silently inserted. Services appearing after the last check can still race activation; failed activation invokes the normal rollback pipeline.

Every method switch is validated in the same transaction as the topology change. An incompatible switch leaves the saved topology and job queue unchanged. The UI keeps the draft range and exceptions visible and disables saving incompatible mappings.

## GRE details

For a range such as `1023-65535 → 1023-65535`, the kernel forwards incoming entry traffic through the GRE interface. Rules preserve destination ports unless an equal-width shifted range was requested. The entry uses SNAT to the GRE address for the return path. The exit forwards to the chosen destination, including loopback application services. Remote destination hosts use narrowly scoped masquerading.

Any connection containing a range uses the kernel path for **all** its mapping rows. Those public intervals must be exclusive on the entry. For shared-port load balancing, use connections containing only individual GRE ports, or one of the socket-based adapters. Many entries can independently map the same ranges to an exit.

Kernel rules live in installation-specific NAT, forwarding and MSS chains. The manager changes IPv4 forwarding only on participating interfaces and enables `route_localnet` only on its owned GRE interfaces when a loopback destination needs it. It journals prior values before changing them and restores unchanged owned values on teardown within the same boot. It does not edit the default route or flush global firewall tables. Do not have another controller concurrently manage these interface settings or owned chains.

An owned systemd unit restores the rules after GRE interfaces start and removes them before the interfaces stop. Partial setup failures remove owned rules and restore saved interface settings. Cleanup is idempotent. Existing NAT-tracked connections may outlive a rule change until they close/time out; the manager does not flush the host conntrack table.

Range health checks verify the GRE peer over the **inner** tunnel and the network unit/chain attachment; they do not demand a listening application on every port. Socket mappings expressed as ranges check every declared listener using socket inventory and sample a transport listener for pool health (one per SSH session). They permit closed destination ports and avoid per-port probe storms. Individual-port mappings still check their destination services. GRE peer health does not establish application throughput or end-user reachability.

## Supported systems and deployment boundaries

Targets must be Debian or Ubuntu Linux with systemd and root management access. The configured public IPv4 must be assigned locally, including for the socket-based adapters. Provider NAT, IPv6, provider firewall APIs and arbitrary operating systems are outside this implementation. Shifted GRE port ranges require kernel 4.18 or newer. Protocol 47 must reach the GRE peer; ordinary public ICMP access is not required, but inner GRE ICMP must be allowed for health checks.

Range intent remains compact in the existing `links.ports` JSON column and immutable job snapshots. No database schema was changed, so no new DDL migration was introduced. Existing integer mappings remain readable, and migration/startup preservation is tested. Older application versions cannot interpret new range records: restore a matching database/key backup when downgrading the application.

References: [Linux DNAT/range syntax](https://man7.org/linux/man-pages/man8/iptables-extensions.8.html), [Linux IPv4 interface settings](https://www.kernel.org/doc/html/latest/networking/ip-sysctl.html), [FRP TCP proxies](https://gofrp.org/en/docs/features/tcp-udp/), [Hysteria forwarding configuration](https://v2.hysteria.network/docs/advanced/Full-Client-Config/).
