"""
Database engine + session factory.

SQLite by default (file: hiring.db next to app.py).
Override with the DATABASE_URL env var to point at Postgres, e.g.:
    set DATABASE_URL=postgresql+psycopg://user:pass@localhost:5432/hiring
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


# ---------- config ----------

# hiring.db lives next to this file's parent (project root)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_SQLITE_PATH = _PROJECT_ROOT / "hiring.db"
_DEFAULT_URL = f"sqlite:///{_DEFAULT_SQLITE_PATH}"

DATABASE_URL: str = os.getenv("DATABASE_URL", _DEFAULT_URL)


# ---------- engine ----------

_is_sqlite = DATABASE_URL.startswith("sqlite")

# SQLite needs check_same_thread=False so Streamlit's reruns can share a connection.
# Postgres ignores this.
_connect_args = {"check_same_thread": False} if _is_sqlite else {}

engine = create_engine(
    DATABASE_URL,
    echo=False,
    future=True,
    connect_args=_connect_args,
)


# ---------- session factory ----------

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    expire_on_commit=False,  # keep objects usable after commit (UI reads attributes)
    future=True,
)


# ---------- declarative base ----------

class Base(DeclarativeBase):
    """All ORM models inherit from this."""
    pass


# ---------- helpers ----------

def get_session() -> Session:
    """
    Return a new Session. Caller is responsible for closing it.
    Used by app.py for the duration of a Streamlit render.
    """
    return SessionLocal()


@contextmanager
def session_scope() -> Iterator[Session]:
    """
    Context manager: commit on success, rollback on error, always close.
    Use for scripts (seed.py, one-off tasks) — not for long-lived UI sessions.
    """
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def init_db() -> None:
    """
    Create all tables if they don't exist.
    Safe to call on every app start.
    """
    # Import models so their tables register with Base.metadata
    from src import models  # noqa: F401

    Base.metadata.create_all(bind=engine)


def drop_all() -> None:
    """
    Drop every table. Used by seed.py --reset and tests.
    Destructive — never call from the app.
    """
    from src import models  # noqa: F401

    Base.metadata.drop_all(bind=engine)