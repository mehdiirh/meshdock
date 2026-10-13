// Public documentation fixtures only. These reserved addresses are not real hosts.
const id = (value) => value.toString(16).padStart(32, "0");
const server = (number, name, region, role, address, x, y) => ({
  id: id(number),
  name,
  region,
  role,
  address,
  host: address,
  ssh_port: 22,
  credential_id: id(20),
  fingerprint: "SHA256:" + "A".repeat(43),
  position: { x, y },
});
const link = (number, entry, exit, method, port = 443) => ({
  id: id(number),
  entry_id: id(entry),
  exit_id: id(exit),
  method,
  enabled: true,
  policy: "roundrobin",
  weight: 1,
  ports: [{ public: port, target: port, host: "127.0.0.1" }],
});

export const topology = {
  revision: 12,
  applied_revision: 12,
  namespace: "abcdef1234",
  servers: [
    server(1, "Atlas gateway", "Tehran · IR", "entry", "192.0.2.10", 50, 30),
    server(2, "Cedar gateway", "Shiraz · IR", "entry", "192.0.2.20", 50, 255),
    server(3, "Orbit gateway", "Tabriz · IR", "entry", "192.0.2.30", 50, 480),
    server(
      4,
      "Bosphorus edge",
      "Istanbul · TR",
      "exit",
      "198.51.100.10",
      670,
      30,
    ),
    server(
      5,
      "Central edge",
      "Frankfurt · DE",
      "exit",
      "198.51.100.20",
      670,
      255,
    ),
    server(6, "Nordic edge", "Helsinki · FI", "exit", "203.0.113.10", 670, 480),
  ],
  links: [
    link(101, 1, 4, "rathole"),
    link(102, 2, 5, "frp_wss"),
    link(103, 3, 6, "gre", 8443),
    link(104, 1, 5, "hysteria2", 8443),
  ],
};

// Shape matches /methods. No binaries, SSH credentials or backend are needed.
export const methods = [
  ["frp_wss", "FRP · WSS", true, "exit-to-entry", "tcp"],
  ["hysteria2", "Hysteria 2", true, "entry-to-exit", "udp"],
  ["gre", "GRE", false, "entry-to-exit", null],
  ["backhaul", "Backhaul", false, "exit-to-entry", "tcp"],
  ["rathole", "Rathole", true, "exit-to-entry", "tcp"],
  ["reverse_ssh", "Reverse SSH", true, "exit-to-entry", "tcp"],
].map(([methodId, name, encrypted, direction, control_protocol]) => ({
  id: methodId,
  name,
  encrypted,
  direction,
  control_protocol,
  protocols: ["tcp"],
  requirements: [],
  mapping: {
    ranges: true,
    exceptions: true,
    native_ranges: methodId === "gre",
    max_ports: 65535,
    max_listener_ports: 65535,
    capacity_basis: methodId === "gre" ? "kernel" : "system_resources",
    protocols: ["tcp"],
    platforms: ["debian", "ubuntu"],
  },
}));
