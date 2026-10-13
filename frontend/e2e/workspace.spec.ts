import { test, expect } from "@playwright/test";
const a = "a".repeat(32),
  b = "b".repeat(32),
  edge = "c".repeat(32);
const topology = {
  revision: 1,
  applied_revision: 1,
  namespace: "d".repeat(10),
  servers: [
    {
      id: a,
      name: "Entry fixture",
      host: "192.0.2.10",
      address: "192.0.2.10",
      ssh_port: 22,
      role: "entry",
      credential_id: "e".repeat(32),
      fingerprint: "SHA256:" + "A".repeat(43),
      region: "West",
      position: { x: 50, y: 100 },
    },
    {
      id: b,
      name: "Exit fixture",
      host: "192.0.2.20",
      address: "192.0.2.20",
      ssh_port: 22,
      role: "exit",
      credential_id: "e".repeat(32),
      fingerprint: "SHA256:" + "A".repeat(43),
      region: "East",
      position: { x: 450, y: 100 },
    },
  ],
  links: [
    {
      id: edge,
      entry_id: a,
      exit_id: b,
      method: "gre",
      enabled: true,
      ports: [{ public: 443, target: 8443, host: "127.0.0.1" }],
      policy: "roundrobin",
      weight: 1,
    },
  ],
};
test.beforeEach(async ({ page }) => {
  await page.route("**/api/v1/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    const values: Record<string, unknown> = {
      "/api/v1/auth/me": { username: "admin", csrf: "fixture", demo: true },
      "/api/v1/topology": topology,
      "/api/v1/jobs": [],
      "/api/v1/methods": [
        { id: "gre", name: "GRE", encrypted: false },
        { id: "rathole", name: "Rathole", encrypted: true },
      ],
    };
    if (route.request().method() === "PUT")
      return route.fulfill({ json: { revision: 2, job_id: "job" } });
    await route.fulfill({ json: values[path] || [] });
  });
  await page.goto("/");
});
test("renders connected nodes and switches a method through the inspector", async ({
  page,
}) => {
  await expect(
    page.getByRole("heading", { name: "Your network, in motion." }),
  ).toBeVisible();
  await expect(page.locator(".server-node")).toHaveCount(2);
  await page.getByText("GRE", { exact: true }).click();
  await page.getByRole("button", { name: "Rathole", exact: true }).click();
  const saved = page.waitForRequest(
    (r) => r.method() === "PUT" && r.url().endsWith("/topology"),
  );
  await page
    .getByRole("button", { name: "Save & deploy", exact: true })
    .click();
  expect((await saved).postDataJSON().links[0].method).toBe("rathole");
  await expect(page.getByRole("status")).toHaveText(
    "Changes saved. Deployment queued.",
  );
});
test("switches appearance and renders Persian RTL without losing the topology", async ({
  page,
}) => {
  await page
    .getByRole("button", { name: "Change appearance", exact: true })
    .click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  await page
    .getByRole("button", { name: "Change language", exact: true })
    .click();
  await expect(page.locator("html")).toHaveAttribute("dir", "rtl");
  await expect(
    page.getByRole("heading", { name: "شبکه شما، در جریان." }),
  ).toBeVisible();
  await expect(page.locator(".server-node")).toHaveCount(2);
});
