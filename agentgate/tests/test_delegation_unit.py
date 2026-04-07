"""Unit tests for delegation, policy, and access request rendering."""
from __future__ import annotations

import json

from agentgate.app.access_provider import CommandRenderingTeleportAccessProvider, derive_scope
from agentgate.app.db import init_db
from agentgate.app.delegation import (
    STATUS_APPROVED,
    STATUS_REVOKED,
    approve_session_mock,
    create_session,
    revoke_session,
)
from agentgate.app.models import PlannedAction
from agentgate.app.policy import action_requires_delegation, delegation_required


def test_scope_derivation_for_restart() -> None:
    actions = [PlannedAction(action="restart_deployment", namespace="prod", deployment="website")]
    scope = derive_scope(actions)
    deployment_scope = scope["kubernetes"]["deployments"][0]
    assert deployment_scope["resource_id"] == "/agentgate-local/kube:ns:deployments.apps/kind-agentgate/prod/website"


def test_role_request_command_rendering() -> None:
    init_db()
    session = create_session(
        task_id="t1",
        delegator_user="alice",
        agent_id="agent-demo",
        reason="restart for fix",
        requested_ttl="1h",
        requested_scope_json=json.dumps({}),
        request_mode="role",
        status="pending_request",
    )
    provider = CommandRenderingTeleportAccessProvider()
    result = provider.create_request(session, [PlannedAction(action="restart_deployment", namespace="default", deployment="my-app")])
    assert "tsh request create" in (result.teleport_request_command or "")
    assert "agentgate-remediator" in (result.teleport_request_command or "")


def test_resource_request_command_rendering() -> None:
    actions = [PlannedAction(action="restart_deployment", namespace="prod", deployment="website")]
    scope = derive_scope(actions)
    session = {
        "session_id": "s1",
        "reason": "restart",
        "requested_ttl": "1h",
        "request_mode": "resource",
        "requested_scope_json": json.dumps(scope),
    }
    provider = CommandRenderingTeleportAccessProvider()
    result = provider.create_request(session, actions)
    assert "--resource" in (result.teleport_request_command or "")
    assert "/agentgate-local/kube:ns:deployments.apps/kind-agentgate/prod/website" in (result.teleport_request_command or "")


def test_policy_baseline_vs_requestable() -> None:
    actions = [PlannedAction(action="restart_deployment", namespace="default", deployment="my-app")]
    assert delegation_required("agent-demo", actions)
    assert action_requires_delegation("agent-demo", actions[0])


def test_delegation_state_transitions() -> None:
    init_db()
    session = create_session(
        task_id="t2",
        delegator_user="bob",
        agent_id="agent-demo",
        reason="fix outage",
        requested_ttl="1h",
        requested_scope_json=json.dumps({}),
        request_mode="mock",
        status="pending_request",
    )
    session = approve_session_mock(session["session_id"])
    assert session["status"] == STATUS_APPROVED
    assert session["expires_at"]
    session = revoke_session(session["session_id"])
    assert session["status"] == STATUS_REVOKED
