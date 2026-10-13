import type { Server, Link, Topology } from "./types";
export function replaceServer(topology: Topology, server: Server): Topology {
  const present = topology.servers.some((item) => item.id === server.id);
  return {
    ...topology,
    servers: present
      ? topology.servers.map((item) => (item.id === server.id ? server : item))
      : [...topology.servers, server],
  };
}
export function removeServer(topology: Topology, id: string): Topology {
  return {
    ...topology,
    servers: topology.servers.filter((server) => server.id !== id),
    links: topology.links.filter(
      (link) => link.entry_id !== id && link.exit_id !== id,
    ),
  };
}
export function replaceLink(topology: Topology, link: Link): Topology {
  return {
    ...topology,
    links: [...topology.links.filter((item) => item.id !== link.id), link],
  };
}

// Applied-only resources are display data, never part of a normal save payload.
export function visibleTopology(topology: Topology) {
  const removals = topology.pending_removals || [];
  const ids = new Set(removals.map((item) => item.link.id));
  return {
    servers: [
      ...topology.servers,
      ...(topology.removal_servers || []).filter(
        (server) =>
          !topology.servers.some((current) => current.id === server.id),
      ),
    ],
    links: [
      ...topology.links.filter((link) => !ids.has(link.id)),
      ...removals.map((item) => item.link),
    ],
  };
}
