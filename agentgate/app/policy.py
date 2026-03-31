"""Per-agent policy guardrails."""
from __future__ import annotations

import json
import os
from typing import Iterable, List, Tuple

from .models import PlannedAction

DEFAULT_ALLOWLIST = {
    "agent-demo": [
        "read_pods",
        "read_logs",
        "describe_deployment",
        "restart_deployment",
    ],
    "agent-readonly": [
        "read_pods",
        "read_logs",
        "describe_deployment",
    ],
}


def _load_allowlist() -> dict[str, List[str]]:
    """Load allowlist from env if present, otherwise use defaults."""
    raw = os.getenv("AGENTGATE_AGENT_ALLOWLIST", "").strip()
    if not raw:
        return DEFAULT_ALLOWLIST
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            return {str(key): list(value) for key, value in data.items()}
    except json.JSONDecodeError:
        pass
    return DEFAULT_ALLOWLIST


def enforce_allowlist(agent_id: str, actions: Iterable[PlannedAction]) -> Tuple[bool, List[str]]:
    """Check if agent is allowed to perform planned actions."""
    allowlist = _load_allowlist()
    allowed_actions = set(allowlist.get(agent_id, []))
    denied = [action.action for action in actions if action.action not in allowed_actions]
    return len(denied) == 0, denied
