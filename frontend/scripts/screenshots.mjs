/** Capture the real UI with isolated fixtures, never the running user's session. */
import { mkdir } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { resolve } from "node:path";
import { chromium, expect } from "@playwright/test";
import { createServer } from "vite";
import { methods, topology } from "./screenshot-fixtures.mjs";

const frontend = fileURLToPath(new URL("../", import.meta.url));
const output = resolve(frontend, "../docs/screenshots");
const origin = "http://127.0.0.1:4188";
const server = await createServer({
  root: frontend,
  envFile: false,
  server: { host: "127.0.0.1", port: 4188, strictPort: true },
});
let browser;
try {
  await server.listen();
  browser = await chromium.launch({
    channel: process.env.SCREENSHOT_BROWSER_CHANNEL || undefined,
  });
  const context = await browser.newContext({
    viewport: { width: 1600, height: 1120 },
    deviceScaleFactor: 1.5,
    locale: "en-US",
    timezoneId: "UTC",
    reducedMotion: "reduce",
    serviceWorkers: "block",
  });
  const unexpected = [];
  await context.route("**/*", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (url.origin !== origin) {
      unexpected.push(request.url());
      return route.abort();
    }
    if (!url.pathname.startsWith("/api/")) return route.continue();
    const responses = {
      "/api/v1/auth/me": {
        username: "demo",
        csrf: "screenshot-fixture",
        demo: true,
      },
      "/api/v1/topology": topology,
      "/api/v1/methods": methods,
      "/api/v1/jobs": [],
    };
    if (request.method() !== "GET" || !(url.pathname in responses)) {
      unexpected.push(`${request.method()} ${url.pathname}`);
      return route.abort();
    }
    return route.fulfill({ json: responses[url.pathname] });
  });
  const page = await context.newPage();
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await mkdir(output, { recursive: true });

  async function capture(name) {
    await page.evaluate(() => document.fonts.ready);
    await expect(
      page.getByRole("link", { name: "MeshDock", exact: true }),
    ).toBeVisible();
    await expect(page.locator(".server-node")).toHaveCount(6);
    await page.mouse.move(10, 10);
    await page.screenshot({
      path: resolve(output, name),
      animations: "disabled",
    });
    console.log(`Captured ${name}`);
  }

  await page.goto(origin);
  await expect(page).toHaveTitle("MeshDock");
  await expect(
    page.getByRole("heading", { name: "Your network, in motion." }),
  ).toBeVisible();
  // Fit only changes the local viewport; it never saves topology.
  await page.getByRole("button", { name: "Fit network to view" }).click();
  await capture("dashboard.png");

  await page
    .getByRole("button", { name: "Change appearance", exact: true })
    .click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  await capture("dashboard-light.png");

  await page
    .getByRole("button", { name: "Change language", exact: true })
    .click();
  await expect(page.locator("html")).toHaveAttribute("dir", "rtl");
  await expect(
    page.getByRole("heading", { name: "شبکه شما، در جریان." }),
  ).toBeVisible();
  await capture("dashboard-persian.png");

  await page.getByRole("button", { name: "تغییر زبان", exact: true }).click();
  await page
    .getByRole("button", { name: "Change appearance", exact: true })
    .click();
  await page.setViewportSize({ width: 1600, height: 1640 });
  const gre = topology.links.find((item) => item.method === "gre");
  await page
    .getByRole("group", { name: `Edge from ${gre.entry_id} to ${gre.exit_id}` })
    .click();
  await page.getByRole("button", { name: "Fit network to view" }).click();
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
  await capture("port-ranges.png");
  await page.getByRole("button", { name: "Rathole", exact: true }).click();
  await expect(
    page.getByText(
      "Individual transport listeners · capacity checked on the server",
    ),
  ).toBeVisible();
  await capture("port-capacity.png");

  if (unexpected.length || errors.length) {
    throw new Error(
      JSON.stringify(
        { unexpectedRequests: unexpected, pageErrors: errors },
        null,
        2,
      ),
    );
  }
  console.log(
    "Saved public-safe MeshDock screenshots. No backend or real server was contacted.",
  );
} finally {
  await browser?.close();
  await server.close();
}
