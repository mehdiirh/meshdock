# Database models and migrations

SQLAlchemy 2 declarative models live in `backend/app/entities.py`. Pydantic request contracts live in `backend/app/schemas.py`. Alembic version files in `backend/alembic/versions/` own schema evolution; the application never calls `create_all`.

Run `uv run python -m app.migrate` from `backend/` before an upgrade. API and worker also invoke this at startup, under a SQLite write lock that serializes concurrent migrators. The schema and Alembic version update commit together.

For a schema change:

1. Modify the SQLAlchemy model.
2. Run `uv run alembic revision --autogenerate -m "describe the change"` against an up-to-date development database.
3. Review generated operations. Add explicit data backfills. Never edit an already released migration.
4. Test upgrading the previous revision with representative existing records, downgrading if supported, repeated startup, and rollback after a failing migration.
5. Run `uv run alembic check` to catch model/schema drift.

SQLite requires batch table-copy operations for some alterations; Alembic is configured for batch mode. Keep changes additive while older workers might exist. Stop API and worker for incompatible upgrades and deploy both from the same release.

Back up through SQLite's backup API before upgrades; preserve the encryption key separately. Restore the matching database/key/application release for destructive downgrades. Migration history belongs in source control; user database files do not.
