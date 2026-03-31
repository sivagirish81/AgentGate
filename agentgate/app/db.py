"""SQLite persistence for AgentGate."""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .config import settings


def _ensure_db_dir() -> None:
    Path(settings.db_path).parent.mkdir(parents=True, exist_ok=True)


@contextmanager
def get_connection() -> Iterator[sqlite3.Connection]:
    """Get a SQLite connection with row factory enabled."""
    _ensure_db_dir()
    conn = sqlite3.connect(settings.db_path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def init_db() -> None:
    """Create tables if they do not exist."""
    _ensure_db_dir()
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS tasks (
                task_id TEXT PRIMARY KEY,
                agent_id TEXT NOT NULL,
                environment TEXT NOT NULL,
                natural_language_task TEXT NOT NULL,
                plan_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                approval_required INTEGER NOT NULL,
                approval_status TEXT NOT NULL,
                execution_status TEXT NOT NULL
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS approvals (
                task_id TEXT PRIMARY KEY,
                required INTEGER NOT NULL,
                status TEXT NOT NULL,
                decided_at TEXT,
                decided_by TEXT
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS audit_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                task_id TEXT NOT NULL,
                agent_id TEXT NOT NULL,
                action TEXT NOT NULL,
                environment TEXT NOT NULL,
                approval_required INTEGER NOT NULL,
                approval_status TEXT NOT NULL,
                execution_status TEXT NOT NULL,
                result_summary TEXT NOT NULL
            )
            """
        )
        conn.commit()
