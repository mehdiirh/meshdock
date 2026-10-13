import { expect, it } from "vitest";
import { removeServer, replaceLink, replaceServer } from "./topology";
import type { Topology, Server, Link } from "./types";
const servers = [
  { id: "a", name: "entry", role: "entry" },
  { id: "b", name: "exit", role: "exit" },
  { id: "c", name: "other", role: "exit" },
] as Server[];
const links = [
  { id: "one", entry_id: "a", exit_id: "b", method: "gre" },
  { id: "two", entry_id: "a", exit_id: "c", method: "rathole" },
] as Link[];
const topology = {
  revision: 2,
  applied_revision: 1,
  namespace: "test",
  servers,
  links,
} satisfies Topology;
it("deleting a server only removes its incident edges", () => {
  const next = removeServer(topology, "b");
  expect(next.links.map((l) => l.id)).toEqual(["two"]);
  expect(topology.links).toHaveLength(2);
});
it("changing an endpoint preserves the server identity and connections", () => {
  const next = replaceServer(topology, {
    ...servers[0],
    address: "192.0.2.99",
  });
  expect(next.servers).toHaveLength(3);
  expect(next.links).toEqual(links);
  expect(next.revision).toBe(2);
});
it("switching a method preserves its mapping and connection identity", () => {
  const next = replaceLink(topology, { ...links[0], method: "hysteria2" });
  expect(next.links).toHaveLength(2);
  expect(next.links.find((l) => l.id === "one")?.method).toBe("hysteria2");
});
