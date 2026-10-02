"""Alembic environment: uses the app's own settings and model metadata."""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app import models  # noqa: F401  (register tables)
from app.config import get_settings
from app.database import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

# CARDIOLENS_DATABASE_URL wins over alembic.ini unless a caller supplied a connection (tests).
if config.attributes.get("connection") is None:
    config.set_main_option("sqlalchemy.url", get_settings().database_url.replace("%", "%%"))

target_metadata = Base.metadata


def _configure(**kw) -> None:
    # render_as_batch lets ALTER-style migrations work on SQLite as well as PostgreSQL.
    context.configure(target_metadata=target_metadata, compare_type=True, render_as_batch=True, **kw)


def run_migrations_offline() -> None:
    _configure(url=config.get_main_option("sqlalchemy.url"), literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    conn = config.attributes.get("connection")
    if conn is not None:
        _configure(connection=conn)
        with context.begin_transaction():
            context.run_migrations()
        return
    engine = engine_from_config(config.get_section(config.config_ini_section, {}), prefix="sqlalchemy.", poolclass=pool.NullPool)
    with engine.connect() as connection:
        _configure(connection=connection)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
