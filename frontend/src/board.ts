import { visibleTopology } from "./topology";
import type { Topology, JumpConnection } from "./types";

export function jumpSourceId(jump: JumpConnection) {
  return (
    jump.source_id ||
    `jump-host:${jump.host.toLowerCase().replace(/\.$/, "")}:${jump.ssh_port}`
  );
}

export function boardTopology(topology: Topology) {
  const visible = visibleTopology(topology);
  const locked = new Set(topology.board_locked_server_ids || []);
  for (const link of visible.links) {
    locked.add(link.entry_id);
    locked.add(link.exit_id);
  }
  const ids = new Set(visible.servers.map((server) => server.id));
  const jumps = (topology.jump_connections || []).filter((jump) =>
    ids.has(jump.target_id),
  );
  for (const jump of jumps) {
    locked.add(jump.target_id);
    if (jump.source_id) locked.add(jump.source_id);
  }
  const hidden = new Set(topology.hidden_server_ids || []);
  return {
    ...visible,
    servers: visible.servers.filter(
      (server) => !hidden.has(server.id) || locked.has(server.id),
    ),
    locked,
    jumps,
  };
}
