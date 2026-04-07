"""Migration tests for additive schema updates."""
from __future__ import annotations

import importlib
import os
import sqlite3
import tempfile

_temp_dir = tempfile.mkdtemp(prefix="agentgate-migrate-test-")
db_path = os.path.join(_temp_dir, "agentgate.db")
os.environ["AGENTGATE_DB_PATH"] = db_path

import agentgate.app.config as config
import agentgate.app.db as db

importlib.reload(config)
importlib.reload(db)


def test_additive_migrations_apply() -> None:
    conn = sqlite3.connect(db_path)
    conn.execute(
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
    conn.execute(
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
    conn.close()

    db.init_db()

    conn = sqlite3.connect(db_path)
    cur = conn.execute("PRAGMA table_info(tasks)")
    columns = {row[1] for row in cur.fetchall()}
    assert "delegation_required" in columns
    assert "delegator_user" in columns
    cur = conn.execute("PRAGMA table_info(audit_events)")
    audit_columns = {row[1] for row in cur.fetchall()}
    assert "delegation_session_id" in audit_columns
    assert "teleport_request_command" in audit_columns
    conn.close()
