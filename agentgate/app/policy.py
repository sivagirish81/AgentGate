"""Per-agent policy guardrails."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Iterable, List, Tuple

from .models import PlannedAction
from .planner import is_write_action

DEFAULT_POLICY = {
    "agent-demo": {
        "baseline": [
            "read_pods",
            "read_logs",
            "describe_deployment",
        ],
        "requestable": [
            "restart_deployment",
        ],
    },
    "agent-readonly": {
        "baseline": [
            "read_pods",
            "read_logs",
            "describe_deployment",
        ],
        "requestable": [],
    },
}


@dataclass(frozen=True)
class AgentPolicy:
    baseline: Tuple[str, ...]
    requestable: Tuple[str, ...]

    @property
    def allowed(self) -> Tuple[str, ...]:
        return tuple(sorted(set(self.baseline) | set(self.requestable)))


def _split_allowlist(allowlist: dict[str, List[str]]) -> dict[str, AgentPolicy]:
    policies: dict[str, AgentPolicy] = {}
    for agent_id, actions in allowlist.items():
        baseline: List[str] = []
        requestable: List[str] = []
        for action in actions:
            if is_write_action(PlannedAction(action=action)):
                requestable.append(action)
            else:
                baseline.append(action)
        policies[agent_id] = AgentPolicy(tuple(baseline), tuple(requestable))
    return policies


def _load_policy() -> dict[str, AgentPolicy]:
    raw_policy = os.getenv("AGENTGATE_AGENT_POLICY", "").strip()
    if raw_policy:
        try:
            data = json.loads(raw_policy)
            if isinstance(data, dict):
                parsed: dict[str, AgentPolicy] = {}
                for agent_id, values in data.items():
                    if not isinstance(values, dict):
                        continue
                    baseline = tuple(values.get("baseline", []))
                    requestable = tuple(values.get("requestable", []))
                    parsed[str(agent_id)] = AgentPolicy(baseline, requestable)
                if parsed:
                    return parsed
        except json.JSONDecodeError:
            pass

    raw_allowlist = os.getenv("AGENTGATE_AGENT_ALLOWLIST", "").strip()
    if raw_allowlist:
        try:
            data = json.loads(raw_allowlist)
            if isinstance(data, dict):
                return _split_allowlist({str(key): list(value) for key, value in data.items()})
        except json.JSONDecodeError:
            pass

    return {
        agent_id: AgentPolicy(tuple(values["baseline"]), tuple(values["requestable"]))
        for agent_id, values in DEFAULT_POLICY.items()
    }


def policy_for(agent_id: str) -> AgentPolicy:
    policies = _load_policy()
    return policies.get(agent_id, AgentPolicy(tuple(), tuple()))


def enforce_allowlist(agent_id: str, actions: Iterable[PlannedAction]) -> Tuple[bool, List[str]]:
    """Check if agent is allowed to perform planned actions."""
    policy = policy_for(agent_id)
    allowed_actions = set(policy.allowed)
    denied = [action.action for action in actions if action.action not in allowed_actions]
    return len(denied) == 0, denied


def delegation_required(agent_id: str, actions: Iterable[PlannedAction]) -> bool:
    policy = policy_for(agent_id)
    requestable = set(policy.requestable)
    return any(action.action in requestable for action in actions)


def action_requires_delegation(agent_id: str, action: PlannedAction) -> bool:
    policy = policy_for(agent_id)
    return action.action in set(policy.requestable)
