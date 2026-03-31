"""Deterministic task planner for AgentGate."""
from __future__ import annotations

import re
from typing import List

from .models import PlannedAction

READ_ONLY_ACTIONS = {"read_pods", "read_logs", "describe_deployment"}
WRITE_ACTIONS = {"restart_deployment"}
ALLOWED_ACTIONS = READ_ONLY_ACTIONS | WRITE_ACTIONS


def _extract_deployment(task_text: str) -> str:
    match = re.search(r"deployment\s+([a-z0-9-]+)", task_text.lower())
    if match:
        return match.group(1)
    return "example-service"


def plan_task(task_text: str) -> List[PlannedAction]:
    """Map a natural language task into an ordered action plan."""
    text = task_text.lower()
    actions: List[PlannedAction] = []
    deployment = _extract_deployment(text)

    if any(keyword in text for keyword in ["pod", "pods", "crashloop", "pending", "evicted"]):
        actions.append(PlannedAction(action="read_pods", namespace="default"))

    if any(keyword in text for keyword in ["log", "logs", "error", "errors", "exception", "stacktrace"]):
        actions.append(PlannedAction(action="read_logs", namespace="default", deployment=deployment))

    if any(keyword in text for keyword in ["describe", "deployment", "rollout", "status", "investigate"]):
        actions.append(PlannedAction(action="describe_deployment", namespace="default", deployment=deployment))

    if any(keyword in text for keyword in ["restart", "rollout restart", "recycle", "redeploy"]):
        actions.append(PlannedAction(action="restart_deployment", namespace="default", deployment=deployment))

    if not actions:
        actions.append(PlannedAction(action="read_pods", namespace="default"))

    return actions


def is_write_action(action: PlannedAction) -> bool:
    return action.action in WRITE_ACTIONS


def is_read_only_action(action: PlannedAction) -> bool:
    return action.action in READ_ONLY_ACTIONS
