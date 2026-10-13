"""Run Alembic under a SQLite write lock to serialize API/worker startup."""

from pathlib import Path

from alembic.config import Config
from sqlalchemy import create_engine

from alembic import command

from . import settings


def configuration():
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    return config


def migrate():
    settings.DATA.mkdir(parents=True, exist_ok=True, mode=0o700)
    engine = create_engine("sqlite:///" + str(settings.DB), connect_args={"timeout": 60})
    try:
        with engine.connect() as connection:
            connection.exec_driver_sql("PRAGMA journal_mode=WAL")
            connection.commit()
            connection.exec_driver_sql("BEGIN IMMEDIATE")
            config = configuration()
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
            connection.commit()
    finally:
        engine.dispose()


if __name__ == "__main__":
    migrate()
