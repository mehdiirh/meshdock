import { describe, expect, it } from "vitest";
import methods from "../e2e/fixtures/methods.json";
import en from "./locales/en.json";
import fa from "./locales/fa.json";
import {
  effectiveSettings,
  settingsValid,
  updateSetting,
} from "./methodSettings";
import type { SettingsSchema } from "./types";

const schema = (id: string) =>
  methods.find((method) => method.id === id)!
    .settings_schema as unknown as SettingsSchema;

describe("adapter-provided settings", () => {
  it("accepts defaults and translates every method and field", () => {
    for (const method of methods) {
      expect(settingsValid(schema(method.id), {})).toBe(true);
      for (const locale of [en, fa]) {
        expect(locale.advanced.methods).toHaveProperty(method.id);
        for (const key of Object.keys(method.settings_schema.properties))
          expect(locale.advanced.fields).toHaveProperty(key);
      }
    }
  });
  it("rejects invalid types, unknown keys and dependencies", () => {
    expect(settingsValid(schema("gre"), { mtu: 100 })).toBe(false);
    expect(settingsValid(schema("gre"), { mtu: "1400" })).toBe(false);
    expect(settingsValid(schema("gre"), { token: "bad" })).toBe(false);
    expect(
      settingsValid(schema("backhaul"), { mux_recievebuffer: 4194304 }),
    ).toBe(false);
    expect(
      settingsValid(schema("backhaul"), {
        transport: "tcpmux",
        mux_streambuffer: 8388608,
      }),
    ).toBe(false);
    expect(settingsValid(schema("rathole"), { heartbeat_interval: 40 })).toBe(
      false,
    );
    expect(settingsValid(schema("hysteria2"), { keepalive_period: 40 })).toBe(
      false,
    );
  });
  it("removes mux overrides when changing transport without dropping other settings", () => {
    const next = updateSetting(
      schema("backhaul"),
      { transport: "tcpmux", mux_recievebuffer: 8388608, dial_timeout: 20 },
      "transport",
      "ws",
    );
    expect(next).toEqual({ transport: "ws", dial_timeout: 20 });
    expect(settingsValid(schema("backhaul"), next)).toBe(true);
  });
  it("keeps boolean false and numeric zero as explicit values", () => {
    const values = effectiveSettings(schema("frp_wss"), {
      tcp_mux: false,
      pool_count: 0,
    });
    expect(values.tcp_mux).toBe(false);
    expect(values.pool_count).toBe(0);
  });
});
