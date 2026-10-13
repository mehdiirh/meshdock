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

| Adapter | Range implementation | Current application limit per connection |
| --- | --- | --- |
| GRE | Kernel DNAT/SNAT for a connection containing any range; compact rules split around exceptions | Up to all 65,535 ports, subject to explicit management/service exclusions |
| Backhaul TCP | Expand remaining ports into native server mappings | 512 ports |
| Rathole Noise | Expand into individual service definitions | 512 ports |
| FRP WSS | Expand into TCP proxies with explicit allowed internal ports | 512 ports |
| Hysteria 2 | Expand into TCP forwarding listeners over its UDP transport | 512 ports |
| Reverse SSH | Expand into restricted reverse forwards | 64 ports |

These are deliberate **application limits**, not claims about each upstream project's theoretical capacity. Reverse SSH is bounded more tightly to keep forwarding arguments and authorized-key options small. Each adapter publishes its capabilities to the UI. All six currently expose **TCP application mappings**; a UDP transport does not imply UDP application forwarding.

## Conflicts and method changes

There is no universally reserved public range. Transport listeners use explicit addresses: public traffic/control listeners bind the configured public IPv4; intermediate listeners bind loopback or a private GRE address. Port numbers can coexist on distinct addresses or different transport protocols.

Before saving, the backend checks overlapping mapping rows, management SSH, shared-pool policy, explicit control listeners, available internal allocations, and the new method's capabilities. Automatic control ports avoid mapped public ranges and other configured control ports. Internal allocations avoid loopback destination services referenced in the topology. Allocations are deterministic plan data; each remote generation preserves its actual manifest for rollback.

Before preparing and activating a server, the helper checks live TCP/UDP listeners, including wildcard binds. An existing process is exempted only when its systemd cgroup belongs to this installation; an old manifest's port number alone is insufficient. An error records the server, address, protocol and port in deployment logs. The operator can add an explicit exception, choose a different control port, or resolve the other service. Exceptions are never silently inserted. Services appearing after the last check can still race activation; failed activation invokes the normal rollback pipeline.

Every method switch is validated in the same transaction as the topology change. An incompatible switch leaves the saved topology and job queue unchanged. The UI keeps the draft range and exceptions visible and disables saving incompatible mappings.

## GRE details

For a range such as `1023-65535 → 1023-65535`, the kernel forwards incoming entry traffic through the GRE interface. Rules preserve destination ports unless an equal-width shifted range was requested. The entry uses SNAT to the GRE address for the return path. The exit forwards to the chosen destination, including loopback application services. Remote destination hosts use narrowly scoped masquerading.

Any connection containing a range uses the kernel path for **all** its mapping rows. Those public intervals must be exclusive on the entry. For shared-port load balancing, use connections containing only individual GRE ports, or one of the socket-based adapters. Many entries can independently map the same ranges to an exit.

Kernel rules live in installation-specific NAT, forwarding and MSS chains. The manager changes IPv4 forwarding only on participating interfaces and enables `route_localnet` only on its owned GRE interfaces when a loopback destination needs it. It journals prior values before changing them and restores unchanged owned values on teardown within the same boot. It does not edit the default route or flush global firewall tables. Do not have another controller concurrently manage these interface settings or owned chains.

An owned systemd unit restores the rules after GRE interfaces start and removes them before the interfaces stop. Partial setup failures remove owned rules and restore saved interface settings. Cleanup is idempotent. Existing NAT-tracked connections may outlive a rule change until they close/time out; the manager does not flush the host conntrack table.

Range health checks verify the GRE peer over the **inner** tunnel and the network unit/chain attachment; they do not demand a listening application on every port. Socket-based adapters still check each configured destination. GRE peer health does not establish application throughput or end-user reachability.

## Supported systems and deployment boundaries

Targets must be Debian or Ubuntu Linux with systemd and root management access. The configured public IPv4 must be assigned locally, including for the socket-based adapters. Provider NAT, IPv6, provider firewall APIs and arbitrary operating systems are outside this implementation. Shifted GRE port ranges require kernel 4.18 or newer. Protocol 47 must reach the GRE peer; ordinary public ICMP access is not required, but inner GRE ICMP must be allowed for health checks.

Range intent remains compact in the existing `links.ports` JSON column and immutable job snapshots. No database schema was changed, so no new DDL migration was introduced. Existing integer mappings remain readable, and migration/startup preservation is tested. Older application versions cannot interpret new range records: restore a matching database/key backup when downgrading the application.

References: [Linux DNAT/range syntax](https://man7.org/linux/man-pages/man8/iptables-extensions.8.html), [Linux IPv4 interface settings](https://www.kernel.org/doc/html/latest/networking/ip-sysctl.html), [FRP TCP proxies](https://gofrp.org/en/docs/features/tcp-udp/), [Hysteria forwarding configuration](https://v2.hysteria.network/docs/advanced/Full-Client-Config/).
