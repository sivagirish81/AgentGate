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
            CREATE TABLE IF NOT EXISTS delegation_sessions (
                session_id TEXT PRIMARY KEY,
                task_id TEXT NOT NULL,
                delegator_user TEXT,
                agent_id TEXT NOT NULL,
                reason TEXT,
                requested_ttl TEXT,
                requested_scope_json TEXT NOT NULL,
                request_mode TEXT,
                teleport_request_id TEXT,
                teleport_request_command TEXT,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                approved_at TEXT,
                revoked_at TEXT,
                expires_at TEXT,
                notes TEXT
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
        _add_column_if_missing(conn, "tasks", "delegator_user", "TEXT")
        _add_column_if_missing(conn, "tasks", "reason", "TEXT")
        _add_column_if_missing(conn, "tasks", "requested_ttl", "TEXT")
        _add_column_if_missing(conn, "tasks", "request_mode", "TEXT")
        _add_column_if_missing(conn, "tasks", "delegation_required", "INTEGER")
        _add_column_if_missing(conn, "audit_events", "delegator_user", "TEXT")
        _add_column_if_missing(conn, "audit_events", "delegation_session_id", "TEXT")
        _add_column_if_missing(conn, "audit_events", "teleport_request_id", "TEXT")
        _add_column_if_missing(conn, "audit_events", "teleport_request_command", "TEXT")
        _add_column_if_missing(conn, "audit_events", "requested_scope_json", "TEXT")
        _add_column_if_missing(conn, "audit_events", "revocation_state", "TEXT")
        conn.commit()


def _add_column_if_missing(conn: sqlite3.Connection, table: str, column: str, column_type: str) -> None:
    cur = conn.execute(f"PRAGMA table_info({table})")
    existing = {row[1] for row in cur.fetchall()}
    if column not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {column_type}")
