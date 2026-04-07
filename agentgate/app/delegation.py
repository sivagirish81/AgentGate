"""Delegation session persistence and transitions."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Optional

from .access_provider import delegation_expires_at
from .db import get_connection


STATUS_NOT_REQUIRED = "not_required"
STATUS_PENDING_REQUEST = "pending_request"
STATUS_PENDING_APPROVAL = "pending_approval"
STATUS_APPROVED = "approved"
STATUS_ACTIVE = "active"
STATUS_REVOKED = "revoked"
STATUS_REJECTED = "rejected"
STATUS_EXPIRED = "expired"


def create_session(
    task_id: str,
    delegator_user: Optional[str],
    agent_id: str,
    reason: Optional[str],
    requested_ttl: Optional[str],
    requested_scope_json: str,
    request_mode: Optional[str],
    status: str,
) -> dict:
    session_id = str(uuid.uuid4())
    created_at = datetime.now(timezone.utc).isoformat()
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO delegation_sessions (
                session_id, task_id, delegator_user, agent_id, reason,
                requested_ttl, requested_scope_json, request_mode, status,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                task_id,
                delegator_user,
                agent_id,
                reason,
                requested_ttl,
                requested_scope_json,
                request_mode,
                status,
                created_at,
            ),
        )
        conn.commit()
    return get_session(session_id) or {}


def get_session(session_id: str) -> dict | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM delegation_sessions WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        return dict(row) if row else None


def get_session_for_task(task_id: str) -> dict | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM delegation_sessions WHERE task_id = ?",
            (task_id,),
        ).fetchone()
        return dict(row) if row else None


def update_session(session_id: str, **updates) -> dict:
    if not updates:
        return get_session(session_id) or {}
    keys = []
    values = []
    for key, value in updates.items():
        keys.append(f"{key} = ?")
        values.append(value)
    values.append(session_id)
    with get_connection() as conn:
        conn.execute(
            f"UPDATE delegation_sessions SET {', '.join(keys)} WHERE session_id = ?",
            tuple(values),
        )
        conn.commit()
    return get_session(session_id) or {}


def mark_pending_approval(session_id: str, teleport_request_id: str | None, teleport_request_command: str | None, notes: str | None) -> dict:
    return update_session(
        session_id,
        status=STATUS_PENDING_APPROVAL,
        teleport_request_id=teleport_request_id,
        teleport_request_command=teleport_request_command,
        notes=notes,
    )


def approve_session_mock(session_id: str) -> dict:
    approved_at = datetime.now(timezone.utc).isoformat()
    session = get_session(session_id) or {}
    expires_at = delegation_expires_at(session.get("requested_ttl"))
    return update_session(
        session_id,
        status=STATUS_APPROVED,
        approved_at=approved_at,
        expires_at=expires_at,
        notes="mock approval recorded",
    )


def reject_session_mock(session_id: str) -> dict:
    return update_session(
        session_id,
        status=STATUS_REJECTED,
        notes="mock rejection recorded",
    )


def revoke_session(session_id: str) -> dict:
    revoked_at = datetime.now(timezone.utc).isoformat()
    return update_session(
        session_id,
        status=STATUS_REVOKED,
        revoked_at=revoked_at,
        notes="delegation revoked",
    )


def touch_active(session_id: str) -> dict:
    return update_session(
        session_id,
        status=STATUS_ACTIVE,
    )


def refresh_expiration(session_id: str) -> dict:
    session = get_session(session_id) or {}
    expires_at = session.get("expires_at")
    if expires_at:
        expires_dt = datetime.fromisoformat(expires_at)
        if expires_dt <= datetime.now(timezone.utc):
            return update_session(session_id, status=STATUS_EXPIRED, notes="delegation expired")
    return session


def parse_scope_json(scope: dict) -> str:
    return json.dumps(scope)
