"""Application-level audit trail."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import List

from .db import get_connection


def record_event(
    task_id: str,
    agent_id: str,
    action: str,
    environment: str,
    approval_required: bool,
    approval_status: str,
    execution_status: str,
    result_summary: str,
    delegator_user: str | None = None,
    delegation_session_id: str | None = None,
    teleport_request_id: str | None = None,
    teleport_request_command: str | None = None,
    requested_scope_json: str | None = None,
    revocation_state: str | None = None,
) -> str:
    timestamp = datetime.now(timezone.utc).isoformat()
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO audit_events (
                timestamp, task_id, agent_id, action, environment,
                approval_required, approval_status, execution_status, result_summary,
                delegator_user, delegation_session_id, teleport_request_id,
                teleport_request_command, requested_scope_json, revocation_state
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                timestamp,
                task_id,
                agent_id,
                action,
                environment,
                int(approval_required),
                approval_status,
                execution_status,
                result_summary,
                delegator_user,
                delegation_session_id,
                teleport_request_id,
                teleport_request_command,
                requested_scope_json,
                revocation_state,
            ),
        )
        conn.commit()
    return timestamp


def list_events() -> List[dict]:
    with get_connection() as conn:
        cur = conn.execute(
            """
            SELECT timestamp, task_id, agent_id, action, environment,
                   approval_required, approval_status, execution_status, result_summary,
                   delegator_user, delegation_session_id, teleport_request_id,
                   teleport_request_command, requested_scope_json, revocation_state
            FROM audit_events
            ORDER BY id DESC
            """
        )
        return [dict(row) for row in cur.fetchall()]
