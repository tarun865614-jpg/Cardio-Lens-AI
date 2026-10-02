from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import StaticPool

from .config import get_settings


class Base(DeclarativeBase):
    pass


def make_engine(url: str):
    if url.startswith("sqlite"):
        kwargs: dict = {"connect_args": {"check_same_thread": False}}
        if url in ("sqlite://", "sqlite:///:memory:"):
            kwargs["poolclass"] = StaticPool
        return create_engine(url, **kwargs)
    return create_engine(url, pool_pre_ping=True)


engine = make_engine(get_settings().database_url)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "migrations"


def alembic_config():
    from alembic.config import Config

    cfg = Config(str(MIGRATIONS_DIR.parent / "alembic.ini"))
    cfg.set_main_option("script_location", str(MIGRATIONS_DIR))
    return cfg


def schema_status(bind=None) -> tuple[str | None, str]:
    """(current revision in the database, head revision in code)."""
    from alembic.runtime.migration import MigrationContext
    from alembic.script import ScriptDirectory

    head = ScriptDirectory.from_config(alembic_config()).get_current_head()
    with (bind or engine).connect() as conn:
        current = MigrationContext.configure(conn).get_current_revision()
    return current, head


def init_db(bind=None) -> None:
    from . import models  # noqa: F401  (register tables)

    if get_settings().schema_mode == "migrate":
        current, head = schema_status(bind)
        if current != head:
            raise RuntimeError(f"Database schema is at {current!r}, code expects {head!r}. Run `alembic upgrade head` first.")
        return
    Base.metadata.create_all(bind=bind or engine)
