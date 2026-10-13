# Tunnel Manager

A self-hosted visual control plane for server-to-server TCP tunnels. Arrange servers on a canvas, connect their handles, choose a transport, and follow each deployment in a persistent event stream.

**FastAPI · SQLAlchemy 2 · Alembic · SQLite · React · TanStack Query · React Flow · react-i18next · uv · Docker Compose**

English and Persian, RTL, light and dark themes. No production infrastructure is included. MIT licensed.

![Interactive demo topology](docs/screenshots/dashboard.png)

## Run an isolated demo

```sh
python3 scripts/setup.py --demo
docker compose up --build -d
```

Open `http://localhost:8080`. The username is `admin`; read the generated password in the owner-only `.env` file. Select “Explore a sample network” to load TEST-NET addresses. Simulation mode never opens SSH connections or changes servers. Do not turn a demo database into a production inventory; start production with a separate data volume.

## Deploy with HTTPS

Point a domain at the control-plane server, then on a fresh checkout:

```sh
python3 scripts/setup.py --origin https://manager.example.com
docker compose --profile tls up --build -d
```

Replace the example domain with your domain. Caddy obtains the certificate; ports 80 and 443 must reach the controller. The web service is also bound to loopback port 8080 for use behind your own reverse proxy. The API and worker are not published directly. Secure cookies are the default. Use one API service and one worker per SQLite database, on a local volume rather than NFS.

The initial password is only used to create the first administrator. Changing `.env` later does not reset an existing account. Use the account screen to change its password. Back up the data volume and master encryption key before upgrades. Never commit `.env`, keys, database files, screenshots containing real infrastructure, or logs.

## Manage a network

1. Store a root password or SSH private key in the vault. Keys may include a passphrase and be reused by several servers.
2. Add entry and exit servers. The management host can differ from the public transport IPv4 address. Discover and independently verify the SSH host fingerprint.
3. Drag a line from an entry's right handle to an exit's left handle. Configure public and destination ports, select a method, optionally select a free transport port such as 443, and save. Deployment is queued immediately.
4. Socket-based connections using the same entry port form a shared HAProxy pool; native GRE ranges require exclusive intervals. Choose round robin, least connections, or ordered failover. Shift-select several entries and exits, then use “Connect selected” for a many-to-many batch.
5. Click an edge to switch methods, or drag its endpoint to another server. Edit a server to replace its host. The old host stays in the reconciliation plan until its managed resources are removed.
6. Open Deployments for persisted, live events. A failed update restores the preceding generation where hosts are reachable. Recovery-required state blocks further changes until rollback can finish.

Port mappings accept equal-width ranges and explicit exceptions. Limits and conflict checks depend on the selected adapter; see [Port mappings](docs/PORT-MAPPINGS.md).

Moving cards only saves layout; it does not deploy. A green revision means the last deployment passed checks, not continuous uptime certification. HAProxy checks continue to steer new connections away from unhealthy backends.

## Transports

Implemented adapters: **GRE, Backhaul TCP, Rathole Noise, reverse SSH, FRP WSS, Hysteria 2 with Salamander**. See [transport research and scoring](docs/TRANSPORTS.md) for the evidence, priorities and limitations. No transport guarantees passage through every national or provider restriction.

Current scope is Debian/Ubuntu with systemd, root SSH, IPv4 endpoints and TCP application mappings. Hysteria uses UDP underneath; GRE uses IP protocol 47. Destination services such as your proxy must already exist. Provider firewalls and NAT rules remain the operator's responsibility. The manager does not change existing Xray routing, Nginx configuration, SSH daemon configuration, or default routes.

## Deployment and recovery

The worker prepares owned generation directories, validates configuration, activates services, checks destinations, then records the applied revision. It has durable receipts, bounded retries, a renewable database lease and monotonic remote fencing epochs. A controller restart compensates an interrupted job before advancing the queue.

Local file-pointer swaps are atomic. **Cross-host activation is not a distributed atomic transaction**, and switching methods can interrupt active TCP connections. A failed or unreachable rollback is visible and blocks new changes. Shared package installation is not undone on rollback. Never assume a tunnel is healthy solely because a process starts: current checks cover service state, TCP destination reachability for socket adapters, and inner GRE peer reachability for native ranges, not the end user's application protocol or an ISP-specific throughput benchmark.

“Clean up tunnels” disables connections and removes managed units, interfaces and firewall rules. Recent generation files remain for recovery; [operations documentation](docs/OPERATIONS.md) describes the explicit full-removal pipeline.

## Development

Requirements: Python 3.12+, uv, Node.js 22+, npm.

```sh
./scripts/dev.sh
```

The frontend runs at `http://127.0.0.1:5177`, API at `http://127.0.0.1:8017`.
The script **always runs in demo mode by default**, even if `.env` or your shell
sets `TM_DEMO=false`. Only this explicit flag enables real server deployments:

```sh
./scripts/dev.sh --prod
```

`--prod` still runs the local development servers; use Docker for hosting the
production service. Saving tunnel changes in this mode can modify your servers.
Stop the current launcher before switching modes; both use the same local ports.

Demo data and encryption keys live in `.data/demo`; real mode uses `.data/prod`.
The launcher overrides `TM_DATA_DIR` and `TM_MASTER_KEY_FILE` to keep these stores
separate. Existing files directly in `.data` are preserved but are not loaded or
automatically migrated. Never copy a demo database into the real store.

If `.env` is absent, the launcher generates it with a unique admin password and
safe demo settings. Existing `.env` files are never overwritten. Read the generated
`TM_ADMIN_PASSWORD` there to sign in. [sample.env](sample.env) documents the available
settings and is also provided as `.env.example`; replace its placeholder password
if configuring manually. Admin credentials only initialize a new database.

```sh
uv sync --project backend --frozen
uv run --project backend --no-sync python backend/compile_locales.py
(cd backend && uv run --no-sync pytest -q)
uv run --project backend --no-sync black --config backend/pyproject.toml --check backend scripts
uv run --project backend --no-sync ruff check --config backend/pyproject.toml backend scripts
(cd frontend && npm ci && npm test && npm run build)
```

Use [AGENTS.md](AGENTS.md), [architecture and adapter contracts](docs/ARCHITECTURE.md), [database migrations](docs/MIGRATIONS.md), and [open decisions](docs/DECISIONS.md) when extending the project. API routes are versioned under `/api/v1`; OpenAPI is at `/api/openapi.json`.

## API access

Create a scoped API key in Access & activity. The plaintext is returned once. Send it in the `Authorization: Bearer` header. Read keys inspect topology, jobs and logs; write keys additionally save layout; admin keys manage infrastructure and credentials. Revocation applies to subsequent calls and active event streams. Browser sessions use HttpOnly cookies and CSRF protection.

## Validation status

This project includes migration, authentication, planner, rollback, recovery, fencing, localization and UI regression tests, plus opt-in real-binary loopback smoke tests. It has **not been validated against production hosts or live filtering conditions**. Linux systemd/firewall behavior needs an isolated staging deployment before production use. Read the [verification record](docs/VERIFICATION.md) for exact test results and [operations](docs/OPERATIONS.md) for the staged rollout procedure.
