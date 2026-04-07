"""Teleport access request providers and scope derivation."""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable, List, Optional

from .config import settings
from .models import PlannedAction
from .planner import is_write_action


@dataclass(frozen=True)
class AccessRequestResult:
    status: str
    teleport_request_id: Optional[str]
    teleport_request_command: Optional[str]
    notes: Optional[str]


def _parse_ttl(ttl: str) -> timedelta:
    if not ttl:
        return timedelta(hours=1)
    ttl = ttl.strip().lower()
    unit = ttl[-1]
    try:
        value = int(ttl[:-1])
    except ValueError:
        return timedelta(hours=1)
    if unit == "h":
        return timedelta(hours=value)
    if unit == "m":
        return timedelta(minutes=value)
    if unit == "s":
        return timedelta(seconds=value)
    return timedelta(hours=1)


def derive_scope(actions: Iterable[PlannedAction]) -> dict:
    """Derive requested scope for planned actions."""
    deployments: List[dict] = []
    for action in actions:
        if action.action == "restart_deployment":
            deployments.append({
                "cluster": settings.teleport_cluster or "<teleport-cluster>",
                "kube_cluster": settings.teleport_kube_cluster or "<kube-cluster>",
                "namespace": action.namespace or "default",
                "name": action.deployment or "example-service",
                "resource_id": build_resource_id(
                    settings.teleport_cluster or "<teleport-cluster>",
                    settings.teleport_kube_cluster or "<kube-cluster>",
                    action.namespace or "default",
                    action.deployment or "example-service",
                ),
            })
    return {
        "requested_actions": [action.action for action in actions],
        "kubernetes": {
            "deployments": deployments,
        },
    }


def build_resource_id(cluster: str, kube_cluster: str, namespace: str, deployment: str) -> str:
    return f"/{cluster}/kube:ns:deployments.apps/{kube_cluster}/{namespace}/{deployment}"


def render_role_request(role: str, reason: str, ttl: str) -> str:
    return (
        f'tsh request create --roles="{role}" '
        f'--reason="{reason}" --ttl="{ttl}"'
    )


def render_resource_request(resource_ids: List[str], reason: str, ttl: str) -> str:
    resources = ",".join(resource_ids)
    return (
        f'tsh request create --resource="{resources}" '
        f'--reason="{reason}" --ttl="{ttl}"'
    )


class TeleportAccessProvider:
    def create_request(self, session: dict, actions: List[PlannedAction]) -> AccessRequestResult:
        raise NotImplementedError

    def refresh(self, session: dict) -> AccessRequestResult:
        raise NotImplementedError

    def revoke(self, session: dict) -> AccessRequestResult:
        raise NotImplementedError


class MockTeleportAccessProvider(TeleportAccessProvider):
    """Deterministic mock provider for tests and local demos."""

    def create_request(self, session: dict, actions: List[PlannedAction]) -> AccessRequestResult:
        request_id = session.get("teleport_request_id") or f"mock-{session['session_id'][:8]}"
        return AccessRequestResult(
            status="pending_approval",
            teleport_request_id=request_id,
            teleport_request_command="mock://approve-delegation",
            notes="mock access request created",
        )

    def refresh(self, session: dict) -> AccessRequestResult:
        return AccessRequestResult(
            status=session.get("status", "pending_request"),
            teleport_request_id=session.get("teleport_request_id"),
            teleport_request_command=session.get("teleport_request_command"),
            notes="mock refresh no-op",
        )

    def revoke(self, session: dict) -> AccessRequestResult:
        return AccessRequestResult(
            status="revoked",
            teleport_request_id=session.get("teleport_request_id"),
            teleport_request_command=session.get("teleport_request_command"),
            notes="mock revocation recorded",
        )


class CommandRenderingTeleportAccessProvider(TeleportAccessProvider):
    """Renders tsh request commands without executing them."""

    def create_request(self, session: dict, actions: List[PlannedAction]) -> AccessRequestResult:
        reason = session.get("reason") or "AgentGate delegated action"
        ttl = session.get("requested_ttl") or settings.default_request_ttl
        mode = session.get("request_mode") or settings.teleport_request_mode
        if mode == "resource":
            scope = json.loads(session.get("requested_scope_json") or "{}")
            deployments = scope.get("kubernetes", {}).get("deployments", [])
            resource_ids = [item.get("resource_id") for item in deployments if item.get("resource_id")]
            command = render_resource_request(resource_ids or ["<resource-id>"], reason, ttl)
        else:
            command = render_role_request(settings.teleport_request_role, reason, ttl)
        return AccessRequestResult(
            status="pending_approval",
            teleport_request_id=session.get("teleport_request_id"),
            teleport_request_command=command,
            notes="run the command to open a Teleport access request",
        )

    def refresh(self, session: dict) -> AccessRequestResult:
        return AccessRequestResult(
            status=session.get("status", "pending_request"),
            teleport_request_id=session.get("teleport_request_id"),
            teleport_request_command=session.get("teleport_request_command"),
            notes="command-rendering provider cannot auto-refresh",
        )

    def revoke(self, session: dict) -> AccessRequestResult:
        return AccessRequestResult(
            status="revoked",
            teleport_request_id=session.get("teleport_request_id"),
            teleport_request_command=session.get("teleport_request_command"),
            notes="local revocation recorded; cancel request in Teleport if needed",
        )


def get_access_provider() -> TeleportAccessProvider:
    if settings.access_provider == "mock":
        return MockTeleportAccessProvider()
    return CommandRenderingTeleportAccessProvider()


def delegation_expires_at(requested_ttl: str | None) -> str:
    ttl = requested_ttl or settings.default_request_ttl
    expires = datetime.now(timezone.utc) + _parse_ttl(ttl)
    return expires.isoformat()


def requires_delegation(actions: Iterable[PlannedAction]) -> bool:
    return any(is_write_action(action) for action in actions)
