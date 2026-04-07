"""FastAPI entrypoint for AgentGate."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import List

from fastapi import FastAPI, HTTPException

from .access_provider import derive_scope, get_access_provider
from .audit import record_event, list_events
from .config import settings
from .db import get_connection, init_db
from .delegation import (
    STATUS_NOT_REQUIRED,
    STATUS_PENDING_APPROVAL,
    STATUS_PENDING_REQUEST,
    STATUS_REJECTED,
    approve_session_mock,
    create_session,
    get_session_for_task,
    mark_pending_approval,
    refresh_expiration,
    reject_session_mock,
    revoke_session,
    update_session,
)
from .executor import execute_actions
from .models import (
    ApprovalResponse,
    AuditEvent,
    ExecuteResponse,
    HealthResponse,
    PlannedAction,
    TaskCreate,
    TaskResponse,
)
from .planner import plan_task
from .policy import delegation_required, enforce_allowlist

app = FastAPI(title="AgentGate", version="0.2.0")


@app.on_event("startup")
def on_startup() -> None:
    init_db()


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok")


@app.post("/tasks", response_model=TaskResponse)
def create_task(payload: TaskCreate) -> TaskResponse:
    actions = plan_task(payload.natural_language_task)
    allowed, denied = enforce_allowlist(payload.agent_id, actions)
    if not allowed:
        record_event(
            task_id=payload.task_id,
            agent_id=payload.agent_id,
            action="policy_denied",
            environment=payload.environment,
            approval_required=False,
            approval_status="not_applicable",
            execution_status="blocked",
            result_summary=f"denied actions: {', '.join(denied)}",
            delegator_user=payload.delegator_user,
        )
        raise HTTPException(status_code=403, detail=f"agent not allowed to perform actions: {', '.join(denied)}")

    delegation_needed = delegation_required(payload.agent_id, actions)
    delegation_status = STATUS_PENDING_REQUEST if delegation_needed else STATUS_NOT_REQUIRED
    scope = derive_scope(actions) if delegation_needed else {}
    requested_scope_json = json.dumps(scope)
    created_at = datetime.now(timezone.utc).isoformat()

    with get_connection() as conn:
        existing = conn.execute("SELECT task_id FROM tasks WHERE task_id = ?", (payload.task_id,)).fetchone()
        if existing:
            raise HTTPException(status_code=400, detail="task_id already exists")

        conn.execute(
            """
            INSERT INTO tasks (
                task_id, agent_id, environment, natural_language_task,
                plan_json, created_at, approval_required, approval_status,
                execution_status, delegator_user, reason, requested_ttl,
                request_mode, delegation_required
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                payload.task_id,
                payload.agent_id,
                payload.environment,
                payload.natural_language_task,
                json.dumps([action.model_dump() for action in actions]),
                created_at,
                int(delegation_needed),
                "pending" if delegation_needed else "not_required",
                "not_started",
                payload.delegator_user,
                payload.reason,
                payload.requested_ttl,
                payload.request_mode,
                int(delegation_needed),
            ),
        )
        conn.commit()

    session = create_session(
        task_id=payload.task_id,
        delegator_user=payload.delegator_user,
        agent_id=payload.agent_id,
        reason=payload.reason,
        requested_ttl=payload.requested_ttl,
        requested_scope_json=requested_scope_json,
        request_mode=payload.request_mode or settings.teleport_request_mode,
        status=delegation_status,
    )

    record_event(
        task_id=payload.task_id,
        agent_id=payload.agent_id,
        action="task_intake",
        environment=payload.environment,
        approval_required=delegation_needed,
        approval_status=delegation_status,
        execution_status="not_started",
        result_summary="task accepted",
        delegator_user=payload.delegator_user,
        delegation_session_id=session.get("session_id"),
        requested_scope_json=requested_scope_json,
    )

    next_steps = _build_next_steps(payload.task_id, delegation_needed)

    return TaskResponse(
        task_id=payload.task_id,
        agent_id=payload.agent_id,
        environment=payload.environment,
        natural_language_task=payload.natural_language_task,
        plan=actions,
        approval_required=delegation_needed,
        approval_status=delegation_status,
        execution_status="not_started",
        delegation_required=delegation_needed,
        delegation_session=session,
        teleport_request=_teleport_request_payload(session),
        next_steps=next_steps,
    )


@app.get("/tasks/{task_id}", response_model=TaskResponse)
def get_task(task_id: str) -> TaskResponse:
    row = _get_task_row(task_id)
    if not row:
        raise HTTPException(status_code=404, detail="task not found")
    plan = json.loads(row["plan_json"])
    session = get_session_for_task(task_id) or {}
    delegation_needed = bool(row["delegation_required"]) if "delegation_required" in row.keys() else bool(row["approval_required"])

    return TaskResponse(
        task_id=row["task_id"],
        agent_id=row["agent_id"],
        environment=row["environment"],
        natural_language_task=row["natural_language_task"],
        plan=plan,
        approval_required=bool(row["approval_required"]),
        approval_status=row["approval_status"],
        execution_status=row["execution_status"],
        delegation_required=delegation_needed,
        delegation_session=session,
        teleport_request=_teleport_request_payload(session),
        next_steps=_build_next_steps(task_id, delegation_needed),
    )


@app.post("/tasks/{task_id}/delegation/request")
def request_delegation(task_id: str) -> dict:
    task = _get_task_row(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="task not found")
    session = get_session_for_task(task_id)
    if not session:
        raise HTTPException(status_code=404, detail="delegation session not found")
    if session.get("status") == STATUS_NOT_REQUIRED:
        raise HTTPException(status_code=400, detail="delegation not required")

    plan = json.loads(task["plan_json"])
    actions = [_normalize_action(action) for action in plan]
    provider = get_access_provider()
    result = provider.create_request(session, actions)
    session = mark_pending_approval(
        session["session_id"],
        result.teleport_request_id,
        result.teleport_request_command,
        result.notes,
    )

    record_event(
        task_id=task_id,
        agent_id=task["agent_id"],
        action="delegation_request",
        environment=task["environment"],
        approval_required=True,
        approval_status=session.get("status", STATUS_PENDING_APPROVAL),
        execution_status=task["execution_status"],
        result_summary=result.notes or "delegation request rendered",
        delegator_user=session.get("delegator_user"),
        delegation_session_id=session.get("session_id"),
        teleport_request_id=session.get("teleport_request_id"),
        teleport_request_command=session.get("teleport_request_command"),
        requested_scope_json=session.get("requested_scope_json"),
    )

    return {
        "delegation_session": session,
        "teleport_request": _teleport_request_payload(session),
        "next_steps": _build_next_steps(task_id, True),
    }


@app.get("/tasks/{task_id}/delegation")
def get_delegation(task_id: str) -> dict:
    session = get_session_for_task(task_id)
    if not session:
        raise HTTPException(status_code=404, detail="delegation session not found")
    return {
        "delegation_session": session,
        "teleport_request": _teleport_request_payload(session),
    }


@app.post("/tasks/{task_id}/delegation/refresh")
def refresh_delegation(task_id: str) -> dict:
    session = get_session_for_task(task_id)
    if not session:
        raise HTTPException(status_code=404, detail="delegation session not found")
    provider = get_access_provider()
    result = provider.refresh(session)
    session = update_session(session["session_id"], status=result.status, notes=result.notes)
    session = refresh_expiration(session["session_id"])
    return {
        "delegation_session": session,
        "teleport_request": _teleport_request_payload(session),
    }


@app.post("/tasks/{task_id}/delegation/revoke")
def revoke_delegation(task_id: str) -> dict:
    session = get_session_for_task(task_id)
    if not session:
        raise HTTPException(status_code=404, detail="delegation session not found")
    provider = get_access_provider()
    result = provider.revoke(session)
    session = revoke_session(session["session_id"])
    record_event(
        task_id=task_id,
        agent_id=session.get("agent_id"),
        action="delegation_revoke",
        environment=_task_environment(task_id),
        approval_required=True,
        approval_status=session.get("status"),
        execution_status="not_started",
        result_summary=result.notes or "delegation revoked",
        delegator_user=session.get("delegator_user"),
        delegation_session_id=session.get("session_id"),
        teleport_request_id=session.get("teleport_request_id"),
        teleport_request_command=session.get("teleport_request_command"),
        requested_scope_json=session.get("requested_scope_json"),
        revocation_state=session.get("status"),
    )
    return {
        "delegation_session": session,
        "teleport_request": _teleport_request_payload(session),
    }


@app.post("/tasks/{task_id}/delegation/approve-mock")
def approve_delegation_mock(task_id: str) -> dict:
    session = _require_mock_delegation(task_id)
    session = approve_session_mock(session["session_id"])
    record_event(
        task_id=task_id,
        agent_id=session.get("agent_id"),
        action="delegation_approve",
        environment=_task_environment(task_id),
        approval_required=True,
        approval_status=session.get("status"),
        execution_status="not_started",
        result_summary="mock delegation approved",
        delegator_user=session.get("delegator_user"),
        delegation_session_id=session.get("session_id"),
        teleport_request_id=session.get("teleport_request_id"),
        teleport_request_command=session.get("teleport_request_command"),
        requested_scope_json=session.get("requested_scope_json"),
    )
    return {"delegation_session": session}


@app.post("/tasks/{task_id}/delegation/reject-mock")
def reject_delegation_mock(task_id: str) -> dict:
    session = _require_mock_delegation(task_id)
    session = reject_session_mock(session["session_id"])
    record_event(
        task_id=task_id,
        agent_id=session.get("agent_id"),
        action="delegation_reject",
        environment=_task_environment(task_id),
        approval_required=True,
        approval_status=STATUS_REJECTED,
        execution_status="not_started",
        result_summary="mock delegation rejected",
        delegator_user=session.get("delegator_user"),
        delegation_session_id=session.get("session_id"),
        teleport_request_id=session.get("teleport_request_id"),
        teleport_request_command=session.get("teleport_request_command"),
        requested_scope_json=session.get("requested_scope_json"),
    )
    return {"delegation_session": session}


@app.post("/approve/{task_id}", response_model=ApprovalResponse)
def approve_task(task_id: str) -> ApprovalResponse:
    session = _require_mock_delegation(task_id)
    session = approve_session_mock(session["session_id"])
    return ApprovalResponse(task_id=task_id, required=True, status=session.get("status"), decided_at=session.get("approved_at"))


@app.post("/reject/{task_id}", response_model=ApprovalResponse)
def reject_task(task_id: str) -> ApprovalResponse:
    session = _require_mock_delegation(task_id)
    session = reject_session_mock(session["session_id"])
    return ApprovalResponse(task_id=task_id, required=True, status=session.get("status"), decided_at=None)


@app.post("/execute/{task_id}", response_model=ExecuteResponse)
def execute_task(task_id: str) -> ExecuteResponse:
    task = _get_task_row(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="task not found")

    plan = json.loads(task["plan_json"])
    actions = [_normalize_action(action) for action in plan]
    allowed, denied = enforce_allowlist(task["agent_id"], actions)
    if not allowed:
        record_event(
            task_id=task_id,
            agent_id=task["agent_id"],
            action="policy_denied",
            environment=task["environment"],
            approval_required=bool(task["approval_required"]),
            approval_status=task["approval_status"],
            execution_status="blocked",
            result_summary=f"denied actions: {', '.join(denied)}",
        )
        raise HTTPException(status_code=403, detail=f"agent not allowed to perform actions: {', '.join(denied)}")

    session = get_session_for_task(task_id)
    if session and session.get("status") == STATUS_PENDING_APPROVAL:
        refresh_expiration(session["session_id"])

    results = execute_actions(
        task_id=task_id,
        agent_id=task["agent_id"],
        environment=task["environment"],
        actions=actions,
        approval_required=bool(task["approval_required"]),
        approval_status=session.get("status") if session else task["approval_status"],
        delegation_session=session,
    )

    execution_status = "completed"
    with get_connection() as conn:
        conn.execute(
            "UPDATE tasks SET execution_status = ? WHERE task_id = ?",
            (execution_status, task_id),
        )
        conn.commit()

    return ExecuteResponse(task_id=task_id, execution_status=execution_status, results=results)


@app.get("/audit", response_model=List[AuditEvent])
def get_audit() -> List[AuditEvent]:
    return list_events()


def _get_task_row(task_id: str):
    with get_connection() as conn:
        return conn.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)).fetchone()


def _normalize_action(data: dict) -> PlannedAction:
    return PlannedAction(
        action=data.get("action"),
        namespace=data.get("namespace"),
        deployment=data.get("deployment"),
        details=data.get("details"),
    )


def _task_environment(task_id: str) -> str:
    row = _get_task_row(task_id)
    return row["environment"] if row else "unknown"


def _teleport_request_payload(session: dict | None) -> dict | None:
    if not session:
        return None
    return {
        "request_id": session.get("teleport_request_id"),
        "request_command": session.get("teleport_request_command"),
        "status": session.get("status"),
    }


def _build_next_steps(task_id: str, delegation_needed: bool) -> List[str]:
    if delegation_needed:
        return [
            f"POST /tasks/{task_id}/delegation/request to render a Teleport access request",
            f"POST /tasks/{task_id}/delegation/refresh after approval",
            f"POST /execute/{task_id} to run write actions",
        ]
    return [f"POST /execute/{task_id} to run actions"]


def _require_mock_delegation(task_id: str) -> dict:
    session = get_session_for_task(task_id)
    if not session:
        raise HTTPException(status_code=404, detail="delegation session not found")
    if settings.access_provider != "mock" and session.get("request_mode") != "mock":
        raise HTTPException(status_code=400, detail="mock-only endpoint")
    return session
