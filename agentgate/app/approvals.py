"""Approval rules and persistence."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable

from .db import get_connection
from .models import PlannedAction
from .planner import is_write_action


APPROVAL_PENDING = "pending"
APPROVAL_APPROVED = "approved"
APPROVAL_REJECTED = "rejected"
APPROVAL_NOT_REQUIRED = "not_required"


def approval_required(environment: str, actions: Iterable[PlannedAction]) -> bool:
    """Determine whether approval is required for the task."""
    has_write = any(is_write_action(action) for action in actions)
    if not has_write:
        return False
    if environment.lower() == "prod":
        return True
    return True


def initial_approval_status(required: bool) -> str:
    return APPROVAL_PENDING if required else APPROVAL_NOT_REQUIRED


def record_approval(task_id: str, required: bool, status: str, decided_by: str | None = None) -> str:
    """Persist approval decision."""
    decided_at = datetime.now(timezone.utc).isoformat()
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO approvals (task_id, required, status, decided_at, decided_by)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(task_id) DO UPDATE SET
                required=excluded.required,
                status=excluded.status,
                decided_at=excluded.decided_at,
                decided_by=excluded.decided_by
            """,
            (task_id, int(required), status, decided_at, decided_by),
        )
        conn.execute(
            """
            UPDATE tasks
            SET approval_status = ?
            WHERE task_id = ?
            """,
            (status, task_id),
        )
        conn.commit()
    return decided_at


def get_approval(task_id: str) -> dict | None:
    with get_connection() as conn:
        cur = conn.execute("SELECT * FROM approvals WHERE task_id = ?", (task_id,))
        row = cur.fetchone()
        if not row:
            return None
        return dict(row)
