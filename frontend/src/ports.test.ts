import { expect, it } from "vitest";
import { compactPorts, mappingSegments, mappingStatus } from "./ports";
import type { MethodInfo } from "./types";

const gre = {
  mapping: { native_ranges: true, max_ports: 65535 },
} as MethodInfo;
const ssh = {
  mapping: { native_ranges: false, max_ports: 65535 },
} as MethodInfo;
const range = {
  public: "1023-65535",
  target: "1023-65535",
  host: "127.0.0.1",
  exclude: [2222, "8080-8081"],
};

it("keeps the full GRE range compact and preserves explicit exceptions", () => {
  expect(mappingSegments(range)).toEqual([
    [1023, 2221],
    [2223, 8079],
    [8082, 65535],
  ]);
  expect(mappingStatus([range], gre, 2222)).toEqual({
    count: 64510,
    native: true,
    error: "",
  });
});
it("switching to a socket transport keeps valid full ranges", () => {
  expect(mappingStatus([range], ssh, 2222).error).toBe("");
  expect(mappingStatus([range], ssh, 2222).native).toBe(false);
  expect(range.exclude).toEqual([2222, "8080-8081"]);
});
it("checks widths, exceptions, and management access", () => {
  expect(mappingStatus([{ ...range, target: "1024-65535" }], gre).error).toBe(
    "rangeWidth",
  );
  expect(mappingStatus([{ ...range, exclude: [22] }], gre).error).toBe(
    "invalidExclusions",
  );
  expect(
    mappingStatus([{ ...range, exclude: ["1023-65535"] }], gre).error,
  ).toBe("emptyMapping");
  expect(mappingStatus([range], gre, 9000).error).toBe("mappingSshConflict");
  expect(mappingStatus([{ ...range, public: "65536" }], gre).error).toBe(
    "invalidRange",
  );
});
it("detects overlapping rows but permits excluded ports in a separate row", () => {
  expect(
    mappingStatus(
      [range, { public: 8080, target: 8080, host: "127.0.0.1" }],
      gre,
    ).error,
  ).toBe("");
  expect(
    mappingStatus(
      [range, { public: 8082, target: 8082, host: "127.0.0.1" }],
      gre,
    ).error,
  ).toBe("mappingOverlap");
});

it("keeps large deployment previews compact without hiding gaps", () => {
  expect(compactPorts([443, 1023, 1024, 1026, 1027, 65535, 443])).toBe(
    "443, 1023-1024, 1026-1027, 65535",
  );
  expect(compactPorts(Array.from({ length: 65535 }, (_, i) => i + 1))).toBe(
    "1-65535",
  );
  expect(compactPorts([])).toBe("");
});
