import { test, expect } from "@playwright/test";
import methods from "./fixtures/methods.json" with { type: "json" };
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
      "/api/v1/methods": methods,
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
  await page.getByRole("group", { name: `Edge from ${a} to ${b}` }).click();
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

test("preserves full ranges and exceptions when switching methods", async ({
  page,
}) => {
  await page.getByRole("group", { name: `Edge from ${a} to ${b}` }).click();
  await page.getByLabel("Entry port 1", { exact: true }).fill("1023-65535");
  await page
    .getByLabel("Destination port 1", { exact: true })
    .fill("1023-65535");
  await page
    .getByLabel("Excluded entry ports 1", { exact: true })
    .fill("2222, 8080-8081");
  await expect(
    page.getByText("64510 TCP ports", { exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Rathole", exact: true }).click();
  await expect(page.getByRole("alert")).toHaveCount(0);
  await expect(
    page.getByText(
      "Individual transport listeners · capacity checked on the server",
    ),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Save & deploy", exact: true }),
  ).toBeEnabled();
  const saved = page.waitForRequest(
    (r) => r.method() === "PUT" && r.url().endsWith("/topology"),
  );
  await page
    .getByRole("button", { name: "Save & deploy", exact: true })
    .click();
  expect((await saved).postDataJSON().links[0].ports[0]).toEqual({
    public: "1023-65535",
    target: "1023-65535",
    host: "127.0.0.1",
    exclude: ["2222", "8080-8081"],
  });
});

test("advanced options validate, keep method drafts, and deploy only selected settings", async ({
  page,
}) => {
  await page.getByRole("group", { name: `Edge from ${a} to ${b}` }).click();
  await page.getByText("Advanced settings", { exact: true }).click();
  const save = page.getByRole("button", { name: "Save & deploy", exact: true });
  await page
    .getByRole("spinbutton", { name: "Tunnel MTU", exact: true })
    .fill("100");
  await expect(save).toBeDisabled();
  await page
    .getByRole("spinbutton", { name: "Tunnel MTU", exact: true })
    .fill("1300");
  await expect(save).toBeEnabled();
  await page.getByRole("button", { name: "Backhaul", exact: true }).click();
  await page.getByRole("button", { name: "tcpmux", exact: true }).click();
  await page
    .getByRole("spinbutton", { name: "Mux receive buffer", exact: true })
    .fill("8388608");
  await page.getByRole("button", { name: "GRE", exact: true }).click();
  await expect(
    page.getByRole("spinbutton", { name: "Tunnel MTU", exact: true }),
  ).toHaveValue("1300");
  await page.getByRole("button", { name: "Backhaul", exact: true }).click();
  await expect(
    page.getByRole("spinbutton", { name: "Mux receive buffer", exact: true }),
  ).toHaveValue("8388608");
  await page.locator(".inspector").evaluate((element) => {
    element.scrollTop = 0;
  });
  await page.screenshot({
    path: test.info().outputPath("advanced-settings.png"),
  });
  const saved = page.waitForRequest(
    (r) => r.method() === "PUT" && r.url().endsWith("/topology"),
  );
  await save.click();
  expect((await saved).postDataJSON().links[0].settings).toEqual({
    transport: "tcpmux",
    mux_recievebuffer: 8388608,
  });
});

test("advanced settings support Persian, defaults, and conditional controls", async ({
  page,
}) => {
  await page.getByRole("group", { name: `Edge from ${a} to ${b}` }).click();
  await page.getByText("Advanced settings", { exact: true }).click();
  await page.getByRole("button", { name: "Backhaul", exact: true }).click();
  await expect(
    page.getByRole("spinbutton", { name: "Mux receive buffer", exact: true }),
  ).toHaveCount(0);
  await page.getByRole("button", { name: "tcpmux", exact: true }).click();
  await expect(
    page.getByRole("spinbutton", { name: "Mux receive buffer", exact: true }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Restore defaults", exact: true })
    .click();
  await expect(
    page.getByRole("spinbutton", { name: "Mux receive buffer", exact: true }),
  ).toHaveCount(0);
  await page
    .getByRole("button", { name: "Change language", exact: true })
    .click();
  await expect(page.locator("html")).toHaveAttribute("dir", "rtl");
  await expect(
    page.getByText("تنظیمات پیشرفته", { exact: true }),
  ).toBeVisible();
  await page.screenshot({
    path: test.info().outputPath("advanced-settings-persian.png"),
  });
});

test("secure transports update TLS and protocol requirements", async ({
  page,
}) => {
  await page.getByRole("group", { name: `Edge from ${a} to ${b}` }).click();
  await page.getByText("Advanced settings", { exact: true }).click();
  await page.getByRole("button", { name: "Backhaul", exact: true }).click();
  await page.getByRole("button", { name: "wssmux", exact: true }).click();
  await expect(page.getByTestId("transport-tls")).toContainText(
    "verifies the peer certificate",
  );
  await expect(
    page.getByRole("spinbutton", { name: "Mux receive buffer", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "wss", exact: true }).click();
  await expect(
    page.getByRole("spinbutton", { name: "Mux receive buffer", exact: true }),
  ).toHaveCount(0);
  await page.getByRole("button", { name: "tcp", exact: true }).click();
  await expect(page.getByTestId("transport-tls")).toHaveCount(0);
  await page.getByRole("button", { name: "FRP", exact: true }).click();
  await page.getByRole("button", { name: "quic", exact: true }).click();
  await expect(page.getByText(/checks both TCP and UDP/)).toBeVisible();
  await page
    .getByRole("spinbutton", { name: "QUIC keepalive", exact: true })
    .fill("30");
  const save = page.getByRole("button", { name: "Save & deploy", exact: true });
  await expect(save).toBeDisabled();
  await page
    .getByRole("spinbutton", { name: "QUIC keepalive", exact: true })
    .fill("15");
  await expect(save).toBeEnabled();
  const saved = page.waitForRequest(
    (r) => r.method() === "PUT" && r.url().endsWith("/topology"),
  );
  await save.click();
  expect((await saved).postDataJSON().links[0].settings).toEqual({
    transport: "quic",
    quic_keepalive: 15,
  });
});

test("failed connections are red and collapsed footer keeps the newest revision", async ({
  page,
}) => {
  await page.route("**/api/v1/topology", (route) =>
    route.fulfill({ json: { ...topology, revision: 2 } }),
  );
  await page.route("**/api/v1/jobs", (route) =>
    route.fulfill({
      json: [
        {
          id: "new",
          revision: 2,
          status: "failed",
          attempt: 3,
          created: 2,
          link_ids: [edge],
          error_code: "ssh_auth",
          error_message:
            "Root SSH authentication failed. Check the saved credential.",
          failure: { server_id: a, code: "ssh_auth", detail: "" },
        },
        {
          id: "old",
          revision: 1,
          status: "succeeded",
          attempt: 1,
          created: 1,
          link_ids: [edge],
        },
      ],
    }),
  );
  await page.reload();
  await expect(page.locator(".react-flow__edge.deployment-failed")).toHaveCount(
    1,
  );
  const bar = page.locator(".jobs-bar");
  await expect(bar).toContainText("r2");
  await bar.click();
  await expect(page.locator(".deployment-error")).toContainText(
    "Root SSH authentication failed",
  );
  await page
    .locator(".job-list button")
    .filter({ hasText: "Revision 1" })
    .click();
  await expect(bar).toContainText("r1");
  await bar.click();
  await expect(bar).toContainText("r2");
  await expect(bar.locator(".status-dot.failed")).toHaveCount(1);
  await page.screenshot({
    path: test.info().outputPath("failed-deployment.png"),
  });
});

test("cancellation stays visible until rollback completes", async ({
  page,
}) => {
  let requested = 0;
  await page.route("**/api/v1/jobs", (route) =>
    route.fulfill({
      json: [
        {
          id: "active",
          revision: 2,
          status: "running",
          attempt: 1,
          created: 2,
          link_ids: [edge],
          cancel_requested: requested,
        },
      ],
    }),
  );
  await page.route("**/api/v1/jobs/active/cancel", (route) => {
    requested++;
    return route.fulfill({ status: 202, json: { job_id: "active" } });
  });
  await page.reload();
  await page.locator(".jobs-bar").click();
  await page
    .getByRole("button", { name: "Cancel & roll back", exact: true })
    .click();
  await expect(page.locator(".deployment-notice")).toContainText(
    "Waiting for the current server operation",
  );
  await expect(
    page.getByRole("button", { name: "Cancel & roll back", exact: true }),
  ).toHaveCount(0);
  await page.locator(".jobs-bar").click();
  await expect(page.locator(".jobs-bar")).toContainText("Cancelling safely");
  expect(requested).toBe(1);
});

test("deployment panel resizes by dragging and keyboard without leaving the viewport", async ({
  page,
}) => {
  const bar = page.locator(".jobs-bar");
  await bar.click();
  const body = page.locator(".jobs-body");
  const handle = page.getByRole("separator", {
    name: /Resize deployment panel/,
  });
  await expect(body).toHaveCSS("height", "420px");
  const bounds = (await handle.boundingBox())!;
  await page.mouse.move(
    bounds.x + bounds.width / 2,
    bounds.y + bounds.height / 2,
  );
  await page.mouse.down();
  await page.mouse.move(
    bounds.x + bounds.width / 2,
    bounds.y + bounds.height / 2 - 140,
    { steps: 5 },
  );
  await page.mouse.up();
  await expect(body).toHaveCSS("height", "560px");
  await handle.focus();
  await page.keyboard.press("ArrowUp");
  await expect(body).toHaveCSS("height", "600px");
  await bar.click();
  await bar.click();
  await expect(body).toHaveCSS("height", "600px");
  await page.setViewportSize({ width: 800, height: 650 });
  await expect(body).toHaveCSS("height", "470px");
  const drawer = (await page.locator(".jobs-drawer").boundingBox())!;
  expect(drawer.y).toBeGreaterThanOrEqual(0);
  expect(drawer.y + drawer.height).toBeLessThanOrEqual(650);
  await page
    .getByRole("button", { name: "Change language", exact: true })
    .click();
  await expect(page.locator("html")).toHaveAttribute("dir", "rtl");
  await expect(page.getByRole("separator")).toHaveAttribute(
    "aria-label",
    /تغییر ارتفاع/,
  );
  await page.screenshot({
    path: test.info().outputPath("resizable-deployments.png"),
  });
});
