import sqlite3

import pytest
from alembic import command
from app import settings
from app.db import connect
from app.migrate import configuration, migrate
from sqlalchemy import create_engine


def test_repeated_migration_preserves_existing_rows(environment):
    with connect(True) as db:
        db.execute("INSERT INTO users VALUES('test','someone','hash',1)")
    migrate()
    migrate()
    with connect() as db:
        assert (
            db.execute("SELECT username FROM users WHERE id='test'").fetchone()[0]
            == "someone"
        )
        assert db.execute("SELECT COUNT(*) FROM alembic_version").fetchone()[0] == 1
    command.check(configuration())


def test_failed_ddl_transaction_preserves_database(environment):
    engine = create_engine("sqlite:///" + str(settings.DB))
    with pytest.raises(RuntimeError):
        with engine.connect() as connection:
            connection.exec_driver_sql("BEGIN IMMEDIATE")
            connection.exec_driver_sql("CREATE TABLE failed_upgrade(id INTEGER)")
            raise RuntimeError("injected migration failure")
    with sqlite3.connect(settings.DB) as db:
        assert (
            db.execute(
                "SELECT name FROM sqlite_master WHERE name='failed_upgrade'"
            ).fetchone()
            is None
        )
    engine.dispose()


def test_upgrade_previous_revision_preserves_data(environment):
    config = configuration()
    command.downgrade(config, "ed9a37d2efc4")
    with connect(True) as database:
        database.execute(
            "INSERT INTO leader(id,owner,until) VALUES(1,'previous-worker',0)"
        )
    migrate()
    with connect() as database:
        row = database.execute("SELECT owner,epoch FROM leader").fetchone()
        assert tuple(row) == ("previous-worker", 0)
    command.check(config)
