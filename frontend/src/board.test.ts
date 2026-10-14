import { expect, it } from "vitest";
import { boardTopology, jumpSourceId } from "./board";
import type { Server, Topology } from "./types";

const topology: Topology = {
  revision: 1,
  applied_revision: 1,
  namespace: "test",
  links: [],
  servers: [{ id: "a" }, { id: "b" }, { id: "c" }] as Server[],
  hidden_server_ids: ["a", "b", "c"],
};
it("keeps unused cards in inventory without altering the topology", () => {
  expect(boardTopology(topology).servers).toHaveLength(0);
  expect(topology.servers).toHaveLength(3);
});
it("always reveals both jump endpoints and retained cleanup endpoints", () => {
  const value: Topology = {
    ...topology,
    board_locked_server_ids: ["c"],
    jump_connections: [
      {
        id: "jump-1",
        source_id: "a",
        target_id: "b",
        host: "192.0.2.1",
        ssh_port: 22,
        retained: true,
      },
    ],
  };
  expect(boardTopology(value).servers).toHaveLength(3);
  expect(boardTopology(value).locked.has("a")).toBe(true);
  expect(boardTopology(value).jumps).toHaveLength(1);
});
it("deduplicates custom jump endpoint nodes while retaining separate routes", () => {
  const jump = {
    id: "jump-1",
    source_id: null,
    target_id: "a",
    host: "Jump.example.test.",
    ssh_port: 22,
    retained: false,
  };
  expect(jumpSourceId(jump)).toBe(
    jumpSourceId({ ...jump, host: "jump.example.test" }),
  );
  expect(jumpSourceId(jump)).not.toBe(
    jumpSourceId({ ...jump, ssh_port: 2222 }),
  );
  const board = boardTopology({ ...topology, jump_connections: [jump] });
  expect(board.servers.map((server) => server.id)).toEqual(["a"]);
});
