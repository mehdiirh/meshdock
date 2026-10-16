import type { MethodInfo, Port, MethodSettings } from "./types";

export function portBounds(value: number | string): [number, number] {
  if (!/^[0-9]{1,5}(-[0-9]{1,5})?$/.test(String(value)))
    throw new Error("invalidRange");
  const parts = String(value).split("-").map(Number);
  const first = parts[0],
    last = parts.at(-1)!;
  if (first < 1 || last > 65535 || first > last)
    throw new Error("invalidRange");
  return [first, last];
}

export function mappingSegments(port: Port): [number, number][] {
  const [first, last] = portBounds(port.public);
  const [target, targetLast] = portBounds(port.target);
  if (last - first !== targetLast - target) throw new Error("rangeWidth");
  const exclusions = (port.exclude || [])
    .map(portBounds)
    .sort((a, b) => a[0] - b[0]);
  if (exclusions.length > 128) throw new Error("invalidExclusions");
  const segments: [number, number][] = [];
  let cursor = first;
  for (const [start, end] of exclusions) {
    if (start < cursor || end > last) throw new Error("invalidExclusions");
    if (start > cursor) segments.push([cursor, start - 1]);
    cursor = end + 1;
  }
  if (cursor <= last) segments.push([cursor, last]);
  if (!segments.length) throw new Error("emptyMapping");
  return segments;
}

export function mappingProtocols(port: Port): ("tcp" | "udp")[] {
  return port.protocol === "both" ? ["tcp", "udp"] : [port.protocol || "tcp"];
}

export function supportedProtocols(
  method?: MethodInfo,
  settings?: MethodSettings,
): string[] {
  const selected = String(
    settings?.transport ??
      method?.settings_schema?.properties.transport?.default ??
      "",
  );
  return (
    method?.transports?.[selected]?.payload_protocols ??
    method?.mapping.protocols ?? ["tcp"]
  );
}

export function mappingStatus(
  ports: Port[],
  method?: MethodInfo,
  sshPort?: number,
  settings?: MethodSettings,
) {
  let count = 0;
  let native = false;
  try {
    const occupied: [number, number, string][] = [];
    const supported = supportedProtocols(method, settings);
    for (const port of ports) {
      const protocols = mappingProtocols(port);
      if (method && protocols.some((p) => !supported.includes(p)))
        throw new Error("mappingProtocolUnsupported");
      const spans = mappingSegments(port);
      const [first, last] = portBounds(port.public);
      native ||=
        !!method?.mapping.native_ranges &&
        (first !== last || !!port.exclude?.length || protocols.includes("udp"));
      for (const protocol of protocols)
        for (const [start, end] of spans) {
          if (
            occupied.some(
              ([a, b, p]) =>
                p === protocol && Math.max(a, start) <= Math.min(b, end),
            )
          )
            throw new Error("mappingOverlap");
          occupied.push([start, end, protocol]);
          if (
            protocol === "tcp" &&
            sshPort &&
            start <= sshPort &&
            sshPort <= end
          )
            throw new Error("mappingSshConflict");
          count += end - start + 1;
        }
    }
    if (method && count > method.mapping.max_ports)
      throw new Error("mappingLimit");
    return { count, native, error: "" };
  } catch (error) {
    return { count, native, error: (error as Error).message };
  }
}

export function compactPorts(ports: number[]): string {
  const sorted = [...new Set(ports)].sort((a, b) => a - b);
  const spans: string[] = [];
  for (let index = 0; index < sorted.length; index++) {
    const first = sorted[index];
    let last = first;
    while (sorted[index + 1] === last + 1) last = sorted[++index];
    spans.push(first === last ? String(first) : `${first}-${last}`);
  }
  return spans.join(", ");
}
