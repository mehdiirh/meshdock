# Architecture and extension contracts

## Boundaries

- `backend/app/entities.py`: typed SQLAlchemy persistence models. Alembic owns schema history.
- `schemas.py`: Pydantic public input contracts; no remote commands in request models.
- `routers/`: versioned HTTP routes, authentication dependencies and public response shaping.
- `topology.py`: topology validation, revision checks, encrypted link material and transactional job enqueueing.
- `planner.py`: deterministic topology-to-host-plan compilation. A plan includes secrets and is private to the worker.
- `methods/`: transport adapters. Each mutates entry/exit plans through one `configure(context, entry, exit)` contract and publishes UI metadata.
- `worker.py`: serialized reconciliation, leases, fencing epochs, bounded retry, receipts and coordinated rollback.
- `ssh.py`: management transport. Verifies a pinned host key before submitting root credentials.
- `remote_agent.py`: standalone standard-library Linux helper. Owns namespaced generations, service links, interfaces and firewall rules.
- `frontend/src/api.ts`: shared HTTP client and React Query policy. Cache keys isolate topology, jobs, logs, credentials, keys and account state.
- `frontend/src/components/`: visual editor, inspectors and management panels. Locale JSON is separate from component logic.

SQLite coordination queries deliberately use explicit short transactions and `BEGIN IMMEDIATE`. SQLAlchemy describes the persistence schema and powers Alembic; the repository currently executes SQLite-specific statements through `db.py`. **PostgreSQL is not supported by changing a URL alone**: lease acquisition, upserts and migration behavior need a dedicated persistence adapter and integration tests. Do not scatter new storage assumptions through UI code.

## Adding a transport

1. Implement `Adapter.configure()` in a new `methods/` module. Register its instance in `REGISTRY`. API validation and method discovery consume that registry.
2. Publish a stable ID, display name, encryption flag, initiation direction, protocols and network requirements. Add localizable caveats when appropriate.
3. Declare `control_protocol` (`tcp`, `udp` or `None`) and the initiation direction. They drive generic port validation and the UI. Reuse `Context.control`, which honors the optional migrated `control_port`, and deterministic internal ports. Only use `tm-<namespace>-*` units, safe filenames and namespaced paths. No system-wide route changes or edits to existing application configs.
4. Return files, service units, listener reservations, firewall rules and health targets. Bind intermediary listeners to loopback or owned overlay addresses, not the whole Internet.
5. Pin upstream binary version, download URL and SHA-256 for each supported architecture in `artifacts.py`. The helper extracts a specific file, never arbitrary archive paths.
6. Store new private material encrypted. Support older link-secret dictionaries when adding fields. Never return secrets in method metadata, plans, errors or exports.
7. Add compiler tests, real-binary loopback tests and isolated Linux provisioning tests before declaring production validation. The shared worker provides retries and rollback; adapters must not bypass it.

The React method picker discovers adapters from `/api/v1/methods`. A method with additional user-configurable settings will need an explicit versioned Pydantic settings schema, persistence migration and reusable form/inspector control; do not accept arbitrary shell fragments or raw systemd snippets.

## Transactions and concurrency

Topology writes compare the submitted revision inside one SQLite write transaction, then update desired state, audit and the immutable job snapshot together. Position-only changes do not alter the infrastructure revision. Queued generations are coalesced; running generations finish or compensate before the next one begins.

The worker renews a durable leader lease. A new owner increments its epoch. Hosts remember the highest epoch and reject stale requests. Before claiming global success the worker verifies its lease again. The host's journal records the previous generation before activation. A lost SSH response is treated as an uncertain outcome and is compensated from that journal.

Preparing a host may install shared packages. Those installations cannot be atomically undone. Activating the owned generation stops/restarts managed services and may interrupt sessions. Recovery can remain blocked by unavailable hosts; no distributed atomicity or exactly-once execution is claimed.

## Localization and style

Backend event/error codes are stable identifiers translated by gettext from `app/locales/{en,fa}/LC_MESSAGES/messages.po`; compile with `compile_locales.py`. Frontend uses react-i18next and `src/locales/{en,fa}.json`. Missing keys are test failures. Addresses, keys and code are isolated LTR inside Persian layouts.

Use Black for Python formatting, Ruff for correctness/import checks and Prettier for frontend formatting. Keep protocol strings in adapters, secrets in the vault, and operational state in durable jobs.
