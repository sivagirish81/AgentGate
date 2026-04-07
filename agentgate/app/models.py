"""Pydantic schemas for AgentGate."""
from __future__ import annotations

from typing import Any, List, Optional

from pydantic import BaseModel, Field


class TaskCreate(BaseModel):
    task_id: str = Field(..., description="Client-supplied task identifier")
    agent_id: str = Field(..., description="Agent identity")
    environment: str = Field(..., description="staging or prod")
    natural_language_task: str = Field(..., description="Task request")
    delegator_user: str | None = Field(None, description="Human delegator identity")
    reason: str | None = Field(None, description="Reason for delegation request")
    requested_ttl: str | None = Field(None, description="Requested delegation TTL (e.g. 1h)")
    request_mode: str | None = Field(None, description="mock, role, or resource")


class PlannedAction(BaseModel):
    action: str
    namespace: Optional[str] = None
    deployment: Optional[str] = None
    details: Optional[dict[str, Any]] = None


class TaskResponse(BaseModel):
    task_id: str
    agent_id: str
    environment: str
    natural_language_task: str
    plan: List[PlannedAction]
    execution_status: str
    approval_required: bool | None = None
    approval_status: str | None = None
    delegation_required: bool
    delegation_session: dict | None = None
    teleport_request: dict | None = None
    next_steps: List[str] | None = None


class ApprovalResponse(BaseModel):
    task_id: str
    required: bool
    status: str
    decided_at: Optional[str]


class ExecuteResponse(BaseModel):
    task_id: str
    execution_status: str
    results: List[dict[str, Any]]


class AuditEvent(BaseModel):
    timestamp: str
    task_id: str
    agent_id: str
    action: str
    environment: str
    approval_required: bool
    approval_status: str
    execution_status: str
    result_summary: str
    delegator_user: str | None = None
    delegation_session_id: str | None = None
    teleport_request_id: str | None = None
    teleport_request_command: str | None = None
    requested_scope_json: str | None = None
    revocation_state: str | None = None


class HealthResponse(BaseModel):
    status: str
