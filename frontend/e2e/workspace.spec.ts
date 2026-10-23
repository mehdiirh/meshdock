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
    page.getByText("64510 port / protocol mappings", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText(
      "Compact ranges · TCP via HAProxy, UDP via kernel forwarding",
      {
        exact: true,
      },
    ),
  ).toBeVisible();
  await expect(
    page.getByText(/Large ranges need enough file descriptors/),
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

for (const operation of ["restore", "retry-removal"] as const) {
  test(`failed removal stays on canvas and ${operation} resolves it`, async ({
    page,
  }) => {
    let state = {
      ...topology,
      revision: 2,
      links: [] as typeof topology.links,
      servers: [topology.servers[0]],
      removal_servers: [topology.servers[1]],
      pending_removals: [{ link: topology.links[0], status: "failed" }],
    };
    let requests = 0;
    await page.route("**/api/v1/topology", (route) =>
      route.fulfill({ json: state }),
    );
    await page.route(`**/api/v1/links/${edge}/${operation}`, async (route) => {
      requests++;
      expect(route.request().postDataJSON()).toEqual({ revision: 2 });
      state =
        operation === "restore"
          ? {
              ...state,
              pending_removals: [],
              removal_servers: [],
              links: topology.links,
              servers: topology.servers,
            }
          : {
              ...state,
              pending_removals: [
                { link: topology.links[0], status: "pending" },
              ],
            };
      await route.fulfill({
        status: 202,
        json: { revision: 3, job_id: "removal-test" },
      });
    });
    await page.reload();
    await expect(page.locator(".server-node")).toHaveCount(2);
    await expect(page.locator(".react-flow__edge.pending-removal")).toHaveCount(
      1,
    );
    await expect(page.locator(".react-flow__edge-text")).toContainText(
      "Removal failed — still deployed",
    );
    await page.locator(".removal-banner").click();
    const panel = page.getByRole("complementary", {
      name: "Unfinished removal",
    });
    await expect(panel).toContainText("Entry fixture → Exit fixture");
    await expect(
      panel.getByRole("button", { name: "Retry removal" }),
    ).toBeEnabled();
    await expect(
      panel.getByRole("button", { name: "Restore connection" }),
    ).toBeEnabled();
    await page.screenshot({
      path: test.info().outputPath(`failed-removal-${operation}.png`),
      animations: "disabled",
    });
    await panel
      .getByRole("button", {
        name: operation === "restore" ? "Restore connection" : "Retry removal",
      })
      .click();
    await page.getByRole("button", { name: "Confirm", exact: true }).click();
    if (operation === "retry-removal") {
      await expect(
        panel.getByRole("button", { name: "Retry removal" }),
      ).toBeDisabled();
      await expect(panel).toContainText("Removal pending");
      await page.reload();
      await expect(
        page.locator(".react-flow__edge.pending-removal"),
      ).toHaveCount(1);
      state = { ...state, pending_removals: [], removal_servers: [] };
      await page.reload();
    }
    await expect(page.locator(".react-flow__edge.pending-removal")).toHaveCount(
      0,
    );
    await expect(page.locator(".react-flow__edge")).toHaveCount(
      operation === "restore" ? 1 : 0,
    );
    expect(requests).toBe(1);
  });
}

test("uncertain removal stays visible and requires recovery before actions", async ({
  page,
}) => {
  await page.route("**/api/v1/topology", (route) =>
    route.fulfill({
      json: {
        ...topology,
        revision: 2,
        links: [],
        pending_removals: [
          { link: topology.links[0], status: "recovery_required" },
        ],
      },
    }),
  );
  await page.reload();
  await page.locator(".removal-banner").click();
  const panel = page.getByRole("complementary", { name: "Unfinished removal" });
  await expect(panel).toContainText("current state is uncertain");
  await expect(
    panel.getByRole("button", { name: "Retry removal" }),
  ).toBeDisabled();
  await expect(
    panel.getByRole("button", { name: "Restore connection" }),
  ).toBeDisabled();
  await page
    .getByRole("button", { name: "Change language", exact: true })
    .click();
  await expect(page.locator("html")).toHaveAttribute("dir", "rtl");
  await expect(page.locator(".removal-panel")).toContainText(
    "وضعیت فعلی آن قطعی نیست",
  );
});

test("saves a jump host and verifies the target through that path", async ({
  page,
}) => {
  await page.route("**/api/v1/credentials", (route) =>
    route.fulfill({
      json: [{ id: "e".repeat(32), name: "Fixture key", kind: "key" }],
    }),
  );
  let discovery: unknown;
  await page.route("**/api/v1/servers/discover", (route) => {
    discovery = route.request().postDataJSON();
    return route.fulfill({ json: { fingerprint: "SHA256:" + "T".repeat(43) } });
  });
  await page
    .locator(".server-node")
    .filter({ hasText: "Exit fixture" })
    .getByRole("button", { name: "Edit server" })
    .click();
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await page
    .getByRole("button", { name: "Via jump host", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "Continue", exact: true }),
  ).toBeDisabled();
  await page
    .locator(".jump-choices button")
    .filter({ hasText: "Entry fixture" })
    .click();
  await expect(
    page.getByLabel("Jump-host address", { exact: true }),
  ).toHaveValue("192.0.2.10");
  await page.screenshot({
    path: test.info().outputPath("ssh-jump-host.png"),
    animations: "disabled",
  });
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Save & deploy", exact: true }),
  ).toBeDisabled();
  await page
    .getByRole("button", { name: "Read host fingerprint", exact: true })
    .click();
  await page.getByLabel("I verified this fingerprint", { exact: true }).check();
  const saved = page.waitForRequest(
    (r) => r.method() === "PUT" && r.url().endsWith("/topology"),
  );
  await page
    .getByRole("button", { name: "Save & deploy", exact: true })
    .click();
  const server = (await saved)
    .postDataJSON()
    .servers.find((s: { id: string }) => s.id === b);
  expect(server.ssh_jump).toEqual({
    host: "192.0.2.10",
    ssh_port: 22,
    username: "root",
    credential_id: "e".repeat(32),
    fingerprint: "SHA256:" + "A".repeat(43),
  });
  expect(server.fingerprint).toBe("SHA256:" + "T".repeat(43));
  expect(discovery).toEqual({
    host: "192.0.2.20",
    ssh_port: 22,
    ssh_jump: server.ssh_jump,
  });
});

test("custom jump keys require trust and direct mode clears the saved path", async ({
  page,
}) => {
  const initial = structuredClone(topology);
  Object.assign(initial.servers[1], {
    ssh_jump: {
      host: "192.0.2.50",
      ssh_port: 2222,
      username: "operator",
      credential_id: "e".repeat(32),
      fingerprint: "SHA256:" + "J".repeat(43),
    },
  });
  await page.route("**/api/v1/topology", (route) =>
    route.fulfill({
      json:
        route.request().method() === "PUT"
          ? { revision: 2, job_id: "job" }
          : initial,
    }),
  );
  await page.route("**/api/v1/credentials", (route) =>
    route.fulfill({
      json: [{ id: "e".repeat(32), name: "Fixture key", kind: "key" }],
    }),
  );
  await page.route("**/api/v1/servers/discover", (route) =>
    route.fulfill({ json: { fingerprint: "SHA256:" + "K".repeat(43) } }),
  );
  await page.reload();
  await page
    .locator(".server-node")
    .filter({ hasText: "Exit fixture" })
    .getByRole("button", { name: "Edit server" })
    .click();
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await page
    .getByLabel("Jump-host address", { exact: true })
    .fill("192.0.2.51");
  const next = page.getByRole("button", { name: "Continue", exact: true });
  await expect(next).toBeDisabled();
  await page
    .getByRole("button", { name: "Read jump-host key", exact: true })
    .click();
  await expect(next).toBeDisabled();
  await page
    .getByLabel("I verified this jump-host fingerprint independently.", {
      exact: true,
    })
    .check();
  await expect(next).toBeEnabled();
  const username = page.getByLabel("Jump-host username", { exact: true });
  await username.fill("invalid user");
  expect(
    await username.evaluate((el: HTMLInputElement) => el.checkValidity()),
  ).toBe(false);
  await username.fill("operator-user");
  expect(
    await username.evaluate((el: HTMLInputElement) => el.checkValidity()),
  ).toBe(true);
  await page.getByRole("button", { name: "Direct", exact: true }).click();
  await next.click();
  await expect(
    page.getByRole("button", { name: "Save & deploy", exact: true }),
  ).toBeDisabled();
  await page
    .getByRole("button", { name: "Read host fingerprint", exact: true })
    .click();
  await page.getByLabel("I verified this fingerprint", { exact: true }).check();
  const saved = page.waitForRequest(
    (r) => r.method() === "PUT" && r.url().endsWith("/topology"),
  );
  await page
    .getByRole("button", { name: "Save & deploy", exact: true })
    .click();
  expect(
    (await saved).postDataJSON().servers.find((s: { id: string }) => s.id === b)
      .ssh_jump,
  ).toBeNull();
});

for (const offline of ["target", "both"]) {
  test(`force deletion reports cleanup and handles ${offline} offline`, async ({
    page,
  }) => {
    let requested = false;
    let skipped = false;
    const operation = () => ({
      id: "force-job",
      revision: 2,
      kind: "force_delete",
      status: offline === "both" && !skipped ? "waiting_cleanup" : "succeeded",
      attempt: 1,
      created: 100,
      error_code:
        offline === "both" && !skipped
          ? "force_delete_attention"
          : "force_delete_orphans",
      link_ids: [edge],
      force_delete: {
        server_id: b,
        server_name: "Exit fixture",
        can_skip: offline === "both" && !skipped,
        hosts: [
          {
            server_id: a,
            name: "Entry fixture",
            host: "192.0.2.10",
            status:
              offline === "target"
                ? "cleaned"
                : skipped
                  ? "skipped"
                  : "unreachable",
          },
          {
            server_id: b,
            name: "Exit fixture",
            host: "192.0.2.20",
            status: offline === "target" || skipped ? "skipped" : "unreachable",
          },
        ],
      },
    });
    await page.route("**/api/v1/topology", (route) =>
      route.fulfill({ json: { ...topology, revision: requested ? 2 : 1 } }),
    );
    await page.route("**/api/v1/jobs", (route) =>
      route.fulfill({ json: requested ? [operation()] : [] }),
    );
    await page.route(`**/api/v1/servers/${b}/force-delete`, (route) => {
      expect(route.request().postDataJSON()).toEqual({ revision: 1 });
      requested = true;
      return route.fulfill({ json: { job_id: "force-job", revision: 2 } });
    });
    await page.route("**/api/v1/jobs/force-job/skip-cleanup", (route) => {
      expect(route.request().postDataJSON()).toEqual({ revision: 2 });
      skipped = true;
      return route.fulfill({ json: { job_id: "force-job" } });
    });
    await page
      .locator(".server-node")
      .filter({ hasText: "Exit fixture" })
      .getByRole("button", { name: "Edit server" })
      .click();
    await page
      .getByRole("button", { name: "Force delete", exact: true })
      .click();
    const force = page.getByRole("button", {
      name: "Force delete",
      exact: true,
    });
    await expect(force).toBeDisabled();
    await page.getByRole("checkbox").check();
    await force.click();
    const report = page.getByRole("region", {
      name: "Endpoint cleanup report",
    });
    await expect(report).toBeVisible();
    await expect(report.locator(".force-host")).toHaveCount(2);
    if (offline === "both") {
      await expect(
        report.getByText("SSH unreachable", { exact: true }),
      ).toHaveCount(2);
      await report
        .getByRole("button", { name: "Skip unreachable cleanup", exact: true })
        .click();
      await expect(
        page.getByText(/Tunnel services and firewall rules may remain there/),
      ).toBeVisible();
      await page.getByRole("button", { name: "Confirm", exact: true }).click();
      await expect(
        report.getByText("Cleanup skipped — resources may remain", {
          exact: true,
        }),
      ).toHaveCount(2);
    } else {
      await expect(report.getByText("Cleaned", { exact: true })).toHaveCount(1);
      await expect(
        report.getByText("Cleanup skipped — resources may remain", {
          exact: true,
        }),
      ).toHaveCount(1);
    }
    await expect(
      report.getByText(/Deletion completed with skipped cleanup/),
    ).toBeVisible();
    await page.screenshot({
      path: test.info().outputPath(`force-delete-${offline}.png`),
      animations: "disabled",
    });
  });
}

test("pending force cleanup survives reload and renders Persian report", async ({
  page,
}) => {
  await page.route("**/api/v1/jobs", (route) =>
    route.fulfill({
      json: [
        {
          id: "force-waiting",
          kind: "force_delete",
          revision: 1,
          created: 100,
          attempt: 1,
          status: "waiting_cleanup",
          error_code: "force_delete_attention",
          link_ids: [edge],
          force_delete: {
            server_id: b,
            server_name: "Exit fixture",
            can_skip: true,
            hosts: [
              {
                server_id: a,
                name: "Entry fixture",
                host: "192.0.2.10",
                status: "unreachable",
              },
              {
                server_id: b,
                name: "Exit fixture",
                host: "192.0.2.20",
                status: "unreachable",
              },
            ],
          },
        },
      ],
    }),
  );
  await page.reload();
  await page
    .getByRole("button", {
      name: "Force deletion needs your attention — review endpoint cleanup",
    })
    .click();
  await expect(
    page.getByRole("region", { name: "Endpoint cleanup report" }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Change language", exact: true })
    .click();
  await expect(page.locator("html")).toHaveAttribute("dir", "rtl");
  await expect(
    page.getByRole("region", { name: "گزارش پاک‌سازی سرورها" }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", {
      name: "رد کردن پاک‌سازی سرورهای دور از دسترس",
      exact: true,
    }),
  ).toBeVisible();
  await page.screenshot({
    path: test.info().outputPath("force-delete-persian.png"),
    animations: "disabled",
  });
});

test("moves an unused card to inventory and restores it after reload without deployment", async ({
  page,
}) => {
  const state = {
    ...structuredClone(topology),
    links: [],
    hidden_server_ids: [] as string[],
    board_locked_server_ids: [],
    jump_connections: [],
  };
  const mutations: string[] = [];
  await page.route("**/api/v1/topology", (route) =>
    route.fulfill({ json: state }),
  );
  await page.route("**/api/v1/servers/*/board", async (route) => {
    mutations.push(route.request().method());
    const id = new URL(route.request().url()).pathname.split("/").at(-2)!;
    const body = route.request().postDataJSON();
    expect(body.revision).toBe(1);
    state.hidden_server_ids = body.hidden
      ? [...state.hidden_server_ids, id]
      : state.hidden_server_ids.filter((value) => value !== id);
    if (body.position)
      state.servers.find((server) => server.id === id)!.position =
        body.position;
    await route.fulfill({
      json: {
        hidden_server_ids: state.hidden_server_ids,
        board_locked_server_ids: [],
        jump_connections: [],
      },
    });
  });
  const deployments: string[] = [];
  page.on("request", (request) => {
    if (request.method() === "PUT" || request.url().endsWith("/reconcile"))
      deployments.push(request.url());
  });
  await page.reload();
  const entry = page.locator(`.react-flow__node[data-id="${a}"]`);
  await entry
    .getByRole("button", { name: "Move to inventory", exact: true })
    .click();
  await expect(entry).toHaveCount(0);
  await expect(
    page.locator(".inventory").getByRole("button", { name: /Entry fixture/ }),
  ).toContainText("Inventory only");
  await expect(page.getByRole("status")).toHaveText(
    "Card moved to inventory. No deployment started.",
  );
  await page.reload();
  await expect(entry).toHaveCount(0);
  await page
    .locator(".inventory")
    .getByRole("button", { name: /Entry fixture/ })
    .click();
  await expect(entry).toBeVisible();
  await entry
    .getByRole("button", { name: "Move to inventory", exact: true })
    .click();
  await expect(entry).toHaveCount(0);
  // Drag restores and persists the drop position in the same presentation request.
  await page
    .locator(".inventory")
    .getByRole("button", { name: /Entry fixture/ })
    .dragTo(page.locator(".canvas-wrap"), {
      targetPosition: { x: 180, y: 160 },
    });
  await expect(entry).toBeVisible();
  expect(mutations).toEqual(["PATCH", "PATCH", "PATCH", "PATCH"]);
  expect(deployments).toEqual([]);
});

test("renders reciprocal jump routes separately from tunnels and locks both endpoints", async ({
  page,
}, testInfo) => {
  const state = {
    ...structuredClone(topology),
    hidden_server_ids: [],
    board_locked_server_ids: [a, b],
    jump_connections: [
      {
        id: "jump-a-b",
        source_id: a,
        target_id: b,
        host: "192.0.2.10",
        ssh_port: 22,
        retained: false,
      },
      {
        id: "jump-b-a",
        source_id: b,
        target_id: a,
        host: "192.0.2.20",
        ssh_port: 22,
        retained: false,
      },
      {
        id: "jump-external",
        source_id: null,
        target_id: a,
        host: "jump.example.test",
        ssh_port: 2222,
        retained: true,
      },
    ],
  };
  await page.route("**/api/v1/topology", (route) =>
    route.fulfill({ json: state }),
  );
  await page.reload();
  await expect(page.locator(".ssh-jump-edge")).toHaveCount(3);
  await expect(page.locator(".react-flow__edge")).toHaveCount(4);
  await expect(page.locator(".jump-node")).toContainText(
    "jump.example.test:2222",
  );
  for (const button of await page
    .getByRole("button", { name: "Move to inventory", exact: true })
    .all())
    await expect(button).toBeDisabled();
  await page.screenshot({
    path: testInfo.outputPath("jump-board-before-click.png"),
  });
  await page
    .locator(".ssh-jump-edge .react-flow__edge-textwrapper")
    .first()
    .click();
  await expect(page.getByRole("status")).toHaveText(
    "SSH hop · management access only",
  );
  await expect(
    page.getByRole("button", { name: "Save & deploy", exact: true }),
  ).toHaveCount(0);
  await page.screenshot({ path: testInfo.outputPath("jump-board-dark.png") });
  await page
    .getByRole("button", { name: "Change appearance", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Change language", exact: true })
    .click();
  await expect(page.locator("html")).toHaveAttribute("dir", "rtl");
  await expect(page.locator(".ssh-jump-edge").first()).toContainText("پرش SSH");
  for (const label of await page
    .locator(".ssh-jump-edge .react-flow__edge-textwrapper")
    .all()) {
    const text = await label.locator("text").boundingBox();
    const background = await label.locator("rect").boundingBox();
    expect(text!.x).toBeGreaterThanOrEqual(background!.x - 1);
    expect(text!.x + text!.width).toBeLessThanOrEqual(
      background!.x + background!.width + 1,
    );
  }
  await page.screenshot({
    path: testInfo.outputPath("jump-board-persian-light.png"),
  });
});

test("connected cards cannot move to inventory", async ({ page }) => {
  for (const button of await page
    .getByRole("button", { name: "Move to inventory", exact: true })
    .all())
    await expect(button).toBeDisabled();
});

test("previews HAProxy listener ranges and resource counts", async ({
  page,
}) => {
  await page.route("**/api/v1/preview", (route) =>
    route.fulfill({
      json: [
        {
          server_id: a,
          units: ["meshdock-fixture-router.service"],
          files: ["haproxy.cfg"],
          ports: [],
          udp_ports: [],
          forwarded_ranges: [],
          socket_ranges: [
            { address: "192.0.2.10", protocol: "tcp", start: 1023, end: 2221 },
            { address: "192.0.2.10", protocol: "tcp", start: 2223, end: 65535 },
          ],
          resources: {
            listeners: 64512,
            nofile: 262144,
            descriptor_budget: 197632,
          },
        },
      ],
    }),
  );
  await page
    .getByRole("button", { name: "Deployment plan", exact: true })
    .click();
  await expect(
    page.getByText("HAProxy listener ranges", { exact: true }),
  ).toBeVisible();
  await expect(page.getByText(/192\.0\.2\.10 · TCP · 1023-2221/)).toBeVisible();
  await expect(page.getByText(/64512/)).toBeVisible();
});

test("each range chooses its protocol and method switches validate without losing intent", async ({
  page,
}) => {
  await page.getByRole("group", { name: `Edge from ${a} to ${b}` }).click();
  const group = page.getByRole("group", {
    name: "Forward traffic 1",
    exact: true,
  });
  await group.getByRole("button", { name: "TCP + UDP", exact: true }).click();
  await page.getByLabel("Entry port 1", { exact: true }).fill("1023-2048");
  await page
    .getByLabel("Destination port 1", { exact: true })
    .fill("3023-4048");
  await page.getByLabel("Excluded entry ports 1", { exact: true }).fill("1100");
  await page.getByRole("button", { name: "Reverse SSH", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Save & deploy", exact: true }),
  ).toBeDisabled();
  await expect(
    group.getByRole("button", { name: "TCP + UDP", exact: true }),
  ).toHaveAttribute("aria-pressed", "true");
  await page.getByRole("button", { name: "GRE", exact: true }).click();
  const saved = page.waitForRequest(
    (r) => r.method() === "PUT" && r.url().endsWith("/topology"),
  );
  await page
    .getByRole("button", { name: "Save & deploy", exact: true })
    .click();
  expect((await saved).postDataJSON().links[0].ports[0]).toMatchObject({
    protocol: "both",
    public: "1023-2048",
    target: "3023-4048",
    exclude: ["1100"],
  });
});

test("saves three independent protocol sections and blocks incompatible Backhaul transports", async ({
  page,
}) => {
  await page.getByRole("group", { name: `Edge from ${a} to ${b}` }).click();
  for (let i = 1; i <= 3; i++) {
    if (i > 1)
      await page
        .getByRole("button", { name: "Add a port", exact: true })
        .click();
    const span = ["1023-2048", "2049-3000", "3001-3500"][i - 1];
    await page.getByLabel(`Entry port ${i}`, { exact: true }).fill(span);
    await page.getByLabel(`Destination port ${i}`, { exact: true }).fill(span);
    await page
      .getByRole("group", { name: `Forward traffic ${i}`, exact: true })
      .getByRole("button", {
        name: ["TCP", "UDP", "TCP + UDP"][i - 1],
        exact: true,
      })
      .click();
  }
  await page.getByRole("button", { name: "Backhaul", exact: true }).click();
  await page.getByText("Advanced settings", { exact: true }).click();
  await page.getByRole("button", { name: "wssmux", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Save & deploy", exact: true }),
  ).toBeDisabled();
  await page.getByRole("button", { name: "tcp", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Save & deploy", exact: true }),
  ).toBeEnabled();
  await page
    .getByRole("group", { name: "Forward traffic 2", exact: true })
    .scrollIntoViewIfNeeded();
  await page.screenshot({
    path: test.info().outputPath("protocol-sections.png"),
  });
  const saved = page.waitForRequest(
    (r) => r.method() === "PUT" && r.url().endsWith("/topology"),
  );
  await page
    .getByRole("button", { name: "Save & deploy", exact: true })
    .click();
  expect(
    (await saved)
      .postDataJSON()
      .links[0].ports.map((p: { protocol?: string }) => p.protocol || "tcp"),
  ).toEqual(["tcp", "udp", "both"]);
});

for (const lang of ["en", "fa"] as const) {
  test(`health failure explains the peer and keeps technical details expandable (${lang})`, async ({
    page,
  }) => {
    const message =
      lang === "en"
        ? "GRE peer 10.253.0.13 did not answer through interface mdaaaaaa3."
        : "همتای GRE با نشانی 10.253.0.13 از طریق رابط mdaaaaaa3 پاسخ نداد.";
    const hint =
      lang === "en"
        ? "Check GRE (IP protocol 47, not port 47)."
        : "عبور GRE (پروتکل IP شمارهٔ ۴۷، نه پورت ۴۷) را بررسی کنید.";
    const detail = JSON.stringify({
      check: "gre_peer",
      interface: "mdaaaaaa3",
      peer: "10.253.0.13",
      phase: "checking",
    });
    await page.route("**/api/v1/jobs", (route) =>
      route.fulfill({
        json: [
          {
            id: "health-failure",
            revision: 2,
            kind: "deploy",
            status: "failed",
            attempt: 3,
            created: 2,
            error_code: "health_failed",
            error_message: message,
            error_hint: hint,
            failure: { server_id: b, code: "health_failed", detail },
            link_ids: [edge],
          },
        ],
      }),
    );
    await page.route("**/api/v1/jobs/health-failure/logs?*", (route) =>
      route.fulfill({
        json: [
          {
            id: 1,
            level: "error",
            code: "health_failed",
            message,
            hint,
            detail,
            server_id: b,
            created: 2,
          },
        ],
      }),
    );
    await page.route("**/api/v1/jobs/health-failure/events?*", (route) =>
      route.fulfill({
        contentType: "text/event-stream",
        body: "event: done\ndata: {}\n\n",
      }),
    );
    await page.reload();
    if (lang === "fa")
      await page
        .getByRole("button", { name: "Change language", exact: true })
        .click();
    await page.locator(".jobs-bar").click();
    await expect(page.locator(".deployment-error")).toContainText(message);
    await expect(page.locator(".deployment-error")).toContainText(hint);
    await expect(page.locator(".deployment-error")).toContainText(
      "Exit fixture",
    );
    await expect(page.locator(".log-hint")).toContainText(hint);
    const details = page.locator(".log-details");
    await expect(details.locator("small")).not.toBeVisible();
    await details
      .getByText(lang === "en" ? "Technical details" : "جزئیات فنی", {
        exact: true,
      })
      .click();
    await expect(details.locator("small")).toBeVisible();
    await expect(details.locator("small")).toHaveAttribute("dir", "ltr");
    await expect(details.locator("small")).toContainText('"check":"gre_peer"');
  });
}
