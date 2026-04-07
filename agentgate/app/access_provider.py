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


def render_request_command(session: dict, actions: List[PlannedAction]) -> str:
    reason = session.get("reason") or "AgentGate delegated action"
    ttl = session.get("requested_ttl") or settings.default_request_ttl
    mode = session.get("request_mode") or settings.teleport_request_mode
    if mode == "resource":
        scope = json.loads(session.get("requested_scope_json") or "{}")
        deployments = scope.get("kubernetes", {}).get("deployments", [])
        resource_ids = [item.get("resource_id") for item in deployments if item.get("resource_id")]
        return render_resource_request(resource_ids or ["<resource-id>"], reason, ttl)
    return render_role_request(settings.teleport_request_role, reason, ttl)


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
        command = render_request_command(session, actions)
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
    if settings.access_provider == "auth_api":
        return AuthApiTeleportAccessProvider()
    return CommandRenderingTeleportAccessProvider()


def delegation_expires_at(requested_ttl: str | None) -> str:
    ttl = requested_ttl or settings.default_request_ttl
    expires = datetime.now(timezone.utc) + _parse_ttl(ttl)
    return expires.isoformat()


def requires_delegation(actions: Iterable[PlannedAction]) -> bool:
    return any(is_write_action(action) for action in actions)


def _tctl_base_command() -> List[str]:
    cmd = ["tctl"]
    if settings.tctl_config_path:
        cmd += ["--config", settings.tctl_config_path]
    if settings.tctl_identity_path:
        cmd += ["--identity", settings.tctl_identity_path]
    if settings.teleport_auth_server:
        cmd += ["--auth-server", settings.teleport_auth_server]
    if settings.teleport_insecure:
        cmd += ["--insecure"]
    return cmd


def _parse_request_state(state: object) -> str:
    if isinstance(state, (int, float)):
        # Teleport returns numeric enums in some builds.
        # Observed mapping: 1 = pending, 2 = approved, 3 = denied.
        mapping = {
            1: "pending_approval",
            2: "approved",
            3: "rejected",
            4: "expired",
        }
        return mapping.get(int(state), "pending_approval")
    normalized = (state or "")
    if not isinstance(normalized, str):
        return "pending_approval"
    normalized = normalized.lower()
    if normalized in {"approved", "approve", "accepted"}:
        return "approved"
    if normalized in {"denied", "rejected"}:
        return "rejected"
    if normalized in {"expired"}:
        return "expired"
    if normalized in {"pending", "pending_approval"}:
        return "pending_approval"
    return "pending_approval"


class AuthApiTeleportAccessProvider(TeleportAccessProvider):
    """Queries Teleport access request status via tctl (auth API)."""

    def create_request(self, session: dict, actions: List[PlannedAction]) -> AccessRequestResult:
        command = session.get("teleport_request_command") or render_request_command(session, actions)
        return AccessRequestResult(
            status="pending_approval",
            teleport_request_id=session.get("teleport_request_id"),
            teleport_request_command=command,
            notes="run the command to open a Teleport access request; attach request id for refresh",
        )

    def refresh(self, session: dict) -> AccessRequestResult:
        request_id = session.get("teleport_request_id")
        if not request_id:
            return AccessRequestResult(
                status=session.get("status", "pending_approval"),
                teleport_request_id=None,
                teleport_request_command=session.get("teleport_request_command"),
                notes="no request id attached; cannot query Teleport",
            )
        cmd = _tctl_base_command() + ["requests", "get", request_id, "--format=json"]
        try:
            import subprocess

            result = subprocess.run(cmd, capture_output=True, text=True, check=False)
            if result.returncode != 0:
                return AccessRequestResult(
                    status=session.get("status", "pending_approval"),
                    teleport_request_id=request_id,
                    teleport_request_command=session.get("teleport_request_command"),
                    notes=f"tctl error: {result.stderr.strip() or 'unable to query request'}",
                )
            payload = json.loads(result.stdout)
            if isinstance(payload, list):
                payload = payload[0] if payload else {}
            state = payload.get("state") or payload.get("spec", {}).get("state") or payload.get("status", "")
            mapped = _parse_request_state(state)
            return AccessRequestResult(
                status=mapped,
                teleport_request_id=request_id,
                teleport_request_command=session.get("teleport_request_command"),
                notes="request status refreshed via tctl auth api",
            )
        except Exception as exc:  # noqa: BLE001
            return AccessRequestResult(
                status=session.get("status", "pending_approval"),
                teleport_request_id=request_id,
                teleport_request_command=session.get("teleport_request_command"),
                notes=f"tctl refresh failed: {exc}",
            )

    def revoke(self, session: dict) -> AccessRequestResult:
        return AccessRequestResult(
            status="revoked",
            teleport_request_id=session.get("teleport_request_id"),
            teleport_request_command=session.get("teleport_request_command"),
            notes="local revocation recorded; revoke in Teleport if needed",
        )
