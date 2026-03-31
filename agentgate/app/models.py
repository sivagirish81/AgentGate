"""Pydantic schemas for AgentGate."""
from __future__ import annotations

from typing import Any, List, Optional

from pydantic import BaseModel, Field


class TaskCreate(BaseModel):
    task_id: str = Field(..., description="Client-supplied task identifier")
    agent_id: str = Field(..., description="Agent identity")
    environment: str = Field(..., description="staging or prod")
    natural_language_task: str = Field(..., description="Task request")


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
    approval_required: bool
    approval_status: str
    execution_status: str


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


class HealthResponse(BaseModel):
    status: str
