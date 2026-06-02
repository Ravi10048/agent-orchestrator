"""DB bootstrap: engine, Base, SessionLocal, get_db(), init_db().

v1 "migrations" = create_all() on startup (idempotent). Production → Alembic
(documented as a next-step). Swap SQLite→Postgres via DATABASE_URL only.
"""
from __future__ import annotations

import os

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.core.config import settings


class Base(DeclarativeBase):
    pass


_is_sqlite = settings.DATABASE_URL.startswith("sqlite")
# SQLite needs check_same_thread=False for FastAPI's threadpool; Postgres ignores it.
connect_args = {"check_same_thread": False} if _is_sqlite else {}
engine = create_engine(settings.DATABASE_URL, connect_args=connect_args, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)

if _is_sqlite:
    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_conn, _record):
        # WAL = concurrent readers alongside a writer; busy_timeout = wait out brief write locks
        # instead of erroring. (FK enforcement is intentionally left OFF — agents may be deleted
        # while a Conversation still references them; the channel dispatcher handles that gracefully.)
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA busy_timeout=5000")
        cur.close()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _ensure_sqlite_dir() -> None:
    """SQLite won't create a missing parent directory — make it before create_all."""
    if not _is_sqlite or ":memory:" in settings.DATABASE_URL:
        return
    path = settings.DATABASE_URL.split("sqlite:///", 1)[-1]
    if path and path != settings.DATABASE_URL:
        directory = os.path.dirname(os.path.abspath(path))
        if directory:
            os.makedirs(directory, exist_ok=True)


# Columns added to existing models after their table was first created. create_all() never ALTERs,
# so on a pre-existing SQLite dev file these would be missing and the first SELECT would raise
# "no such column". The shim below adds them idempotently (additive, nullable only). Prod = Alembic.
_ADDITIVE_SQLITE_COLUMNS = [
    ("conversations", "workflow_id", "INTEGER"),
    ("conversations", "curr_agent", "VARCHAR(120)"),
]


def _migrate_sqlite_add_columns(eng=engine) -> None:
    """Idempotently ADD COLUMN any known additive/nullable column missing from an existing SQLite
    table (a dev convenience so reviewers don't have to delete app.db). No-op on a fresh DB (the
    column already exists after create_all) and on non-SQLite engines (Postgres -> Alembic)."""
    if eng.dialect.name != "sqlite":
        return
    with eng.begin() as conn:
        for table, column, ddl in _ADDITIVE_SQLITE_COLUMNS:
            existing = {row[1] for row in conn.exec_driver_sql(f"PRAGMA table_info({table})")}
            if existing and column not in existing:  # table present but column missing -> add it
                conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")


def init_db() -> None:
    import app.models  # noqa: F401 — register all models on Base.metadata
    _ensure_sqlite_dir()
    Base.metadata.create_all(bind=engine)
    _migrate_sqlite_add_columns()  # additive columns on a pre-existing SQLite file
