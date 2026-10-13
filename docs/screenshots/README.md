# MeshDock screenshots

These images are rendered from the actual frontend using six fictional servers and RFC 5737 documentation addresses. They illustrate the UI; they are not evidence of a live deployment, traffic volume, or performance benchmark.

| Image | View |
| --- | --- |
| `dashboard.png` | English topology, dark appearance. |
| `dashboard-light.png` | The same topology in light appearance. |
| `dashboard-persian.png` | Persian text and RTL layout. |
| `port-ranges.png` | GRE range configuration with explicit exceptions. |
| `port-capacity.png` | The same draft switched to Rathole with capacity guidance. |

## Recreate the gallery

From the repository root:

```sh
cd frontend
npm ci
npx playwright install chromium
npm run screenshots
```

If Chrome is already installed, it can be used without downloading Playwright's Chromium:

```sh
SCREENSHOT_BROWSER_CHANNEL=chrome npm run screenshots
```

The capture script starts its own Vite server at `127.0.0.1:4188`, opens an isolated browser context, and closes both afterward. Leave that port free. It uses committed fixtures from `frontend/scripts/screenshot-fixtures.mjs`, intercepts all API requests, rejects unexpected requests, and does not load your `.env`, browser session, credentials, or database. No backend, SSH access, or deployed servers are required.

Screenshots use a 1.5× pixel density, locally bundled fonts, English/Persian locales, and reduced motion. The range views are taller to show transport choices and mapping details together. Changes in browser version can produce small rendering differences.

Before committing a new capture, open every image to check that text is readable, the UI is settled, and no personal information appears. Keep images as genuine UI captures; do not invent controls, status readings, traffic metrics, or capabilities.
