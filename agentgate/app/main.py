"""FastAPI entrypoint for AgentGate."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import List

from fastapi import FastAPI, HTTPException

from .approvals import (
    APPROVAL_APPROVED,
    APPROVAL_PENDING,
    APPROVAL_REJECTED,
    approval_required,
    get_approval,
    initial_approval_status,
    record_approval,
)
from .audit import record_event, list_events
from .db import get_connection, init_db
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
from .policy import enforce_allowlist

app = FastAPI(title="AgentGate", version="0.1.0")


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
        )
        raise HTTPException(status_code=403, detail=f"agent not allowed to perform actions: {', '.join(denied)}")
    approval_needed = approval_required(payload.environment, actions)
    approval_status = initial_approval_status(approval_needed)
    created_at = datetime.now(timezone.utc).isoformat()

    with get_connection() as conn:
        existing = conn.execute("SELECT task_id FROM tasks WHERE task_id = ?", (payload.task_id,)).fetchone()
        if existing:
            raise HTTPException(status_code=400, detail="task_id already exists")

        conn.execute(
            """
            INSERT INTO tasks (
                task_id, agent_id, environment, natural_language_task,
                plan_json, created_at, approval_required, approval_status, execution_status
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                payload.task_id,
                payload.agent_id,
                payload.environment,
                payload.natural_language_task,
                json.dumps([action.model_dump() for action in actions]),
                created_at,
                int(approval_needed),
                approval_status,
                "not_started",
            ),
        )
        conn.commit()

    record_event(
        task_id=payload.task_id,
        agent_id=payload.agent_id,
        action="task_intake",
        environment=payload.environment,
        approval_required=approval_needed,
        approval_status=approval_status,
        execution_status="not_started",
        result_summary="task accepted",
    )

    if approval_needed:
        record_approval(payload.task_id, True, approval_status)

    return TaskResponse(
        task_id=payload.task_id,
        agent_id=payload.agent_id,
        environment=payload.environment,
        natural_language_task=payload.natural_language_task,
        plan=actions,
        approval_required=approval_needed,
        approval_status=approval_status,
        execution_status="not_started",
    )


@app.get("/tasks/{task_id}", response_model=TaskResponse)
def get_task(task_id: str) -> TaskResponse:
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="task not found")
        plan = json.loads(row["plan_json"])

    return TaskResponse(
        task_id=row["task_id"],
        agent_id=row["agent_id"],
        environment=row["environment"],
        natural_language_task=row["natural_language_task"],
        plan=plan,
        approval_required=bool(row["approval_required"]),
        approval_status=row["approval_status"],
        execution_status=row["execution_status"],
    )


@app.post("/approve/{task_id}", response_model=ApprovalResponse)
def approve_task(task_id: str) -> ApprovalResponse:
    task = _get_task_row(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="task not found")
    if task["approval_status"] == APPROVAL_REJECTED:
        raise HTTPException(status_code=400, detail="task already rejected")

    decided_at = record_approval(task_id, bool(task["approval_required"]), APPROVAL_APPROVED, decided_by="human")
    record_event(
        task_id=task_id,
        agent_id=task["agent_id"],
        action="approval",
        environment=task["environment"],
        approval_required=bool(task["approval_required"]),
        approval_status=APPROVAL_APPROVED,
        execution_status=task["execution_status"],
        result_summary="approved",
    )
    return ApprovalResponse(task_id=task_id, required=bool(task["approval_required"]), status=APPROVAL_APPROVED, decided_at=decided_at)


@app.post("/reject/{task_id}", response_model=ApprovalResponse)
def reject_task(task_id: str) -> ApprovalResponse:
    task = _get_task_row(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="task not found")

    decided_at = record_approval(task_id, bool(task["approval_required"]), APPROVAL_REJECTED, decided_by="human")
    record_event(
        task_id=task_id,
        agent_id=task["agent_id"],
        action="approval",
        environment=task["environment"],
        approval_required=bool(task["approval_required"]),
        approval_status=APPROVAL_REJECTED,
        execution_status=task["execution_status"],
        result_summary="rejected",
    )
    return ApprovalResponse(task_id=task_id, required=bool(task["approval_required"]), status=APPROVAL_REJECTED, decided_at=decided_at)


@app.post("/execute/{task_id}", response_model=ExecuteResponse)
def execute_task(task_id: str) -> ExecuteResponse:
    task = _get_task_row(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="task not found")

    approval = get_approval(task_id)
    approval_status = task["approval_status"]
    if approval and approval.get("status"):
        approval_status = approval["status"]

    if task["approval_required"] and approval_status not in {APPROVAL_APPROVED}:
        raise HTTPException(status_code=400, detail="approval required")

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
            approval_status=approval_status,
            execution_status="blocked",
            result_summary=f"denied actions: {', '.join(denied)}",
        )
        raise HTTPException(status_code=403, detail=f"agent not allowed to perform actions: {', '.join(denied)}")
    results = execute_actions(
        task_id=task_id,
        agent_id=task["agent_id"],
        environment=task["environment"],
        actions=actions,
        approval_required=bool(task["approval_required"]),
        approval_status=approval_status,
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
