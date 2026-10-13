import { describe, it, expect } from "vitest";
import en from "./locales/en.json";
import fa from "./locales/fa.json";
function keys(value: Record<string, unknown>, prefix = ""): string[] {
  return Object.entries(value)
    .flatMap(([key, entry]) =>
      typeof entry === "object" && entry !== null
        ? keys(entry as Record<string, unknown>, prefix + key + ".")
        : [prefix + key],
    )
    .sort();
}
describe("locale catalogs", () => {
  it("provide identical message keys", () =>
    expect(keys(fa)).toEqual(keys(en)));
  it("contain no empty translations", () => {
    for (const language of [en, fa])
      expect(JSON.stringify(language)).not.toContain(':""');
  });
});
