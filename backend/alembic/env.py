from alembic import context
from app import settings
from app.entities import Base
from sqlalchemy import create_engine, pool

config = context.config
target_metadata = Base.metadata


def run_migrations(connection):
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        render_as_batch=True,
        compare_type=True,
        transactional_ddl=True,
    )
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    context.configure(
        url="sqlite:///" + str(settings.DB),
        target_metadata=target_metadata,
        literal_binds=True,
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()
elif config.attributes.get("connection") is not None:
    run_migrations(config.attributes["connection"])
else:
    engine = create_engine("sqlite:///" + str(settings.DB), poolclass=pool.NullPool)
    with engine.connect() as connection:
        connection.exec_driver_sql("BEGIN IMMEDIATE")
        run_migrations(connection)
        connection.commit()
