"""Application configuration."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _load_env_file() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    env_path = repo_root / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


_load_env_file()


@dataclass(frozen=True)
class Settings:
    """Runtime settings loaded from environment variables."""

    db_path: str = os.getenv("AGENTGATE_DB_PATH", "./data/agentgate.db")
    teleport_proxy: str = os.getenv("AGENTGATE_TELEPORT_PROXY", "")
    teleport_cluster: str = os.getenv("AGENTGATE_TELEPORT_CLUSTER", "")
    teleport_kube_cluster: str = os.getenv("AGENTGATE_TELEPORT_KUBE_CLUSTER", "")
    tbot_kubeconfig_path: str = os.getenv("AGENTGATE_TBOT_KUBECONFIG", "./.tbot/kubeconfig")
    tbot_identity_path: str = os.getenv("AGENTGATE_TBOT_IDENTITY", "./.tbot/identity")
    elevated_kubeconfig_path: str = os.getenv("AGENTGATE_ELEVATED_KUBECONFIG", "")
    access_provider: str = os.getenv("AGENTGATE_ACCESS_PROVIDER", "command")
    teleport_request_mode: str = os.getenv("AGENTGATE_TELEPORT_REQUEST_MODE", "role")
    teleport_request_role: str = os.getenv("AGENTGATE_TELEPORT_REQUEST_ROLE", "agentgate-remediator")
    default_request_ttl: str = os.getenv("AGENTGATE_DEFAULT_REQUEST_TTL", "1h")
    tctl_config_path: str = os.getenv("AGENTGATE_TCTL_CONFIG", "")
    tctl_identity_path: str = os.getenv("AGENTGATE_TCTL_IDENTITY", "")
    teleport_auth_server: str = os.getenv("AGENTGATE_TELEPORT_AUTH_SERVER", "")
    teleport_insecure: bool = os.getenv("AGENTGATE_TELEPORT_INSECURE", "false").lower() == "true"
    use_mock_executor: bool = os.getenv("AGENTGATE_USE_MOCK_EXECUTOR", "false").lower() == "true"


settings = Settings()
