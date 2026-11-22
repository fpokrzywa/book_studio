"""SQLite engine factory with the project's connection policy (docs/DATA_MODEL.md section 1)."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker


def _fold(value: Any) -> Any:
    """Unicode-aware case folding for search (SQLite's lower() is ASCII-only)."""
    return value.casefold() if isinstance(value, str) else value


def create_sqlite_engine(db_path: Path) -> Engine:
    engine = create_engine(
        f"sqlite:///{db_path.as_posix()}",
        connect_args={"check_same_thread": False, "timeout": 5},
    )

    @event.listens_for(engine, "connect")
    def _on_connect(dbapi_conn: sqlite3.Connection, _record: Any) -> None:
        # Let SQLAlchemy own transaction boundaries (pysqlite's implicit BEGIN is unreliable).
        dbapi_conn.isolation_level = None
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA journal_mode=WAL")
        # FULL: every commit is durable across power loss. Single-user write volume is tiny.
        cur.execute("PRAGMA synchronous=FULL")
        cur.execute("PRAGMA busy_timeout=5000")
        cur.close()
        dbapi_conn.create_function("pbs_fold", 1, _fold, deterministic=True)

    @event.listens_for(engine, "begin")
    def _on_begin(conn: Any) -> None:
        # Take the write lock up front: avoids SQLITE_BUSY lock-upgrade failures under WAL.
        conn.exec_driver_sql("BEGIN IMMEDIATE")

    return engine


class Database:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self._sessions = sessionmaker(bind=engine, expire_on_commit=False)

    @contextmanager
    def tx(self) -> Iterator[Session]:
        """One transaction: commit on success, roll back on any exception."""
        with self._sessions() as session, session.begin():
            yield session

    def dispose(self) -> None:
        self.engine.dispose()
