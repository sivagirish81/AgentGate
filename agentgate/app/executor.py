"""Execution orchestration for AgentGate."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List

from .audit import record_event
from .config import settings
from .models import PlannedAction
from .planner import is_write_action
from .teleport_client import TeleportClient


@dataclass
class ExecutionResult:
    action: str
    status: str
    summary: str


class TeleportExecutor:
    """Executor that relies on Teleport-issued credentials."""

    def __init__(self) -> None:
        self.client = TeleportClient()

    def run(self, action: PlannedAction) -> ExecutionResult:
        if action.action == "read_pods":
            result = self.client.read_pods(action.namespace or "default")
        elif action.action == "read_logs":
            result = self.client.read_logs(action.namespace or "default", action.deployment or "example-service")
        elif action.action == "describe_deployment":
            result = self.client.describe_deployment(action.namespace or "default", action.deployment or "example-service")
        elif action.action == "restart_deployment":
            result = self.client.restart_deployment(action.namespace or "default", action.deployment or "example-service")
        else:
            return ExecutionResult(action.action, "failed", "unsupported action")

        status = "success" if result.returncode == 0 else "failed"
        return ExecutionResult(action.action, status, result.summary())


class MockExecutor:
    """Fallback executor for local demos without Teleport or Kubernetes."""

    def run(self, action: PlannedAction) -> ExecutionResult:
        summary = f"mocked {action.action}"
        if action.deployment:
            summary += f" on deployment {action.deployment}"
        return ExecutionResult(action.action, "success", summary)


def get_executor() -> TeleportExecutor | MockExecutor:
    if settings.use_mock_executor:
        return MockExecutor()
    return TeleportExecutor()


def execute_actions(
    task_id: str,
    agent_id: str,
    environment: str,
    actions: List[PlannedAction],
    approval_required: bool,
    approval_status: str,
) -> List[dict[str, Any]]:
    """Execute actions and record audit events."""
    executor = get_executor()
    results: List[dict[str, Any]] = []

    for action in actions:
        if is_write_action(action) and approval_status != "approved":
            results.append({
                "action": action.action,
                "status": "blocked",
                "summary": "approval required",
            })
            continue

        result = executor.run(action)
        record_event(
            task_id=task_id,
            agent_id=agent_id,
            action=action.action,
            environment=environment,
            approval_required=approval_required,
            approval_status=approval_status,
            execution_status=result.status,
            result_summary=result.summary,
        )
        results.append({
            "action": result.action,
            "status": result.status,
            "summary": result.summary,
        })

    return results
