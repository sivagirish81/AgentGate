"""Execution orchestration for AgentGate."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List

from .audit import record_event
from .config import settings
from .delegation import (
    STATUS_ACTIVE,
    STATUS_APPROVED,
    STATUS_EXPIRED,
    refresh_expiration,
    touch_active,
)
from .models import PlannedAction
from .policy import action_requires_delegation
from .teleport_client import TeleportClient


@dataclass
class ExecutionResult:
    action: str
    status: str
    summary: str


class TeleportExecutor:
    """Executor that relies on Teleport-issued credentials."""

    def __init__(self, kubeconfig_path: str | None = None) -> None:
        self.client = TeleportClient(kubeconfig_path=kubeconfig_path)

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
    delegation_session: dict | None,
) -> List[dict[str, Any]]:
    """Execute actions and record audit events."""
    results: List[dict[str, Any]] = []
    baseline_executor = TeleportExecutor()
    elevated_executor = TeleportExecutor(kubeconfig_path=settings.elevated_kubeconfig_path) if settings.elevated_kubeconfig_path else None
    mock_executor = MockExecutor()

    for action in actions:
        requires_delegation = action_requires_delegation(agent_id, action)
        if requires_delegation:
            session = delegation_session or {}
            refreshed = refresh_expiration(session.get("session_id")) if session.get("session_id") else session
            status = (refreshed or session).get("status")
            if status in {STATUS_EXPIRED}:
                record_event(
                    task_id=task_id,
                    agent_id=agent_id,
                    action=action.action,
                    environment=environment,
                    approval_required=approval_required,
                    approval_status=approval_status,
                    execution_status="blocked",
                    result_summary="delegation expired",
                    delegator_user=(delegation_session or {}).get("delegator_user"),
                    delegation_session_id=(delegation_session or {}).get("session_id"),
                    teleport_request_id=(delegation_session or {}).get("teleport_request_id"),
                    teleport_request_command=(delegation_session or {}).get("teleport_request_command"),
                    requested_scope_json=(delegation_session or {}).get("requested_scope_json"),
                    revocation_state=(delegation_session or {}).get("status"),
                )
                results.append({
                    "action": action.action,
                    "status": "blocked",
                    "summary": "delegation expired",
                })
                continue
            if status not in {STATUS_APPROVED, STATUS_ACTIVE}:
                record_event(
                    task_id=task_id,
                    agent_id=agent_id,
                    action=action.action,
                    environment=environment,
                    approval_required=approval_required,
                    approval_status=approval_status,
                    execution_status="blocked",
                    result_summary="delegation required",
                    delegator_user=(delegation_session or {}).get("delegator_user"),
                    delegation_session_id=(delegation_session or {}).get("session_id"),
                    teleport_request_id=(delegation_session or {}).get("teleport_request_id"),
                    teleport_request_command=(delegation_session or {}).get("teleport_request_command"),
                    requested_scope_json=(delegation_session or {}).get("requested_scope_json"),
                    revocation_state=(delegation_session or {}).get("status"),
                )
                results.append({
                    "action": action.action,
                    "status": "blocked",
                    "summary": "delegation required",
                })
                continue
            if not settings.elevated_kubeconfig_path:
                if settings.use_mock_executor:
                    result = mock_executor.run(action)
                else:
                    record_event(
                        task_id=task_id,
                        agent_id=agent_id,
                        action=action.action,
                        environment=environment,
                        approval_required=approval_required,
                        approval_status=approval_status,
                        execution_status="blocked",
                        result_summary="delegation approved but no elevated kubeconfig configured",
                        delegator_user=(delegation_session or {}).get("delegator_user"),
                        delegation_session_id=(delegation_session or {}).get("session_id"),
                        teleport_request_id=(delegation_session or {}).get("teleport_request_id"),
                        teleport_request_command=(delegation_session or {}).get("teleport_request_command"),
                        requested_scope_json=(delegation_session or {}).get("requested_scope_json"),
                        revocation_state=(delegation_session or {}).get("status"),
                    )
                    results.append({
                        "action": action.action,
                        "status": "blocked",
                        "summary": "delegation approved but no elevated kubeconfig configured",
                    })
                    continue
            else:
                if elevated_executor is None:
                    record_event(
                        task_id=task_id,
                        agent_id=agent_id,
                        action=action.action,
                        environment=environment,
                        approval_required=approval_required,
                        approval_status=approval_status,
                        execution_status="failed",
                        result_summary="elevated kubeconfig unavailable",
                        delegator_user=(delegation_session or {}).get("delegator_user"),
                        delegation_session_id=(delegation_session or {}).get("session_id"),
                        teleport_request_id=(delegation_session or {}).get("teleport_request_id"),
                        teleport_request_command=(delegation_session or {}).get("teleport_request_command"),
                        requested_scope_json=(delegation_session or {}).get("requested_scope_json"),
                        revocation_state=(delegation_session or {}).get("status"),
                    )
                    results.append({
                        "action": action.action,
                        "status": "failed",
                        "summary": "elevated kubeconfig unavailable",
                    })
                    continue
                can_i = elevated_executor.client.auth_can_i("patch", "deployments.apps", action.namespace or "default")
                if can_i.returncode != 0 or "yes" not in can_i.stdout.lower():
                    record_event(
                        task_id=task_id,
                        agent_id=agent_id,
                        action=action.action,
                        environment=environment,
                        approval_required=approval_required,
                        approval_status=approval_status,
                        execution_status="blocked",
                        result_summary="elevated identity lacks permission (kubectl auth can-i failed)",
                        delegator_user=(delegation_session or {}).get("delegator_user"),
                        delegation_session_id=(delegation_session or {}).get("session_id"),
                        teleport_request_id=(delegation_session or {}).get("teleport_request_id"),
                        teleport_request_command=(delegation_session or {}).get("teleport_request_command"),
                        requested_scope_json=(delegation_session or {}).get("requested_scope_json"),
                        revocation_state=(delegation_session or {}).get("status"),
                    )
                    results.append({
                        "action": action.action,
                        "status": "blocked",
                        "summary": "elevated identity lacks permission (kubectl auth can-i failed)",
                    })
                    continue
                result = elevated_executor.run(action)
            if session.get("session_id"):
                touch_active(session["session_id"])
        else:
            if settings.use_mock_executor:
                result = mock_executor.run(action)
            else:
                result = baseline_executor.run(action)
        record_event(
            task_id=task_id,
            agent_id=agent_id,
            action=action.action,
            environment=environment,
            approval_required=approval_required,
            approval_status=approval_status,
            execution_status=result.status,
            result_summary=result.summary,
            delegator_user=(delegation_session or {}).get("delegator_user"),
            delegation_session_id=(delegation_session or {}).get("session_id"),
            teleport_request_id=(delegation_session or {}).get("teleport_request_id"),
            teleport_request_command=(delegation_session or {}).get("teleport_request_command"),
            requested_scope_json=(delegation_session or {}).get("requested_scope_json"),
            revocation_state=(delegation_session or {}).get("status"),
        )
        results.append({
            "action": result.action,
            "status": result.status,
            "summary": result.summary,
        })

    return results
