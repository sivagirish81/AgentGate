"""Application configuration."""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    """Runtime settings loaded from environment variables."""

    db_path: str = os.getenv("AGENTGATE_DB_PATH", "./data/agentgate.db")
    teleport_proxy: str = os.getenv("AGENTGATE_TELEPORT_PROXY", "")
    teleport_cluster: str = os.getenv("AGENTGATE_TELEPORT_CLUSTER", "")
    teleport_kube_cluster: str = os.getenv("AGENTGATE_TELEPORT_KUBE_CLUSTER", "")
    tbot_kubeconfig_path: str = os.getenv("AGENTGATE_TBOT_KUBECONFIG", "./.tbot/kubeconfig")
    tbot_identity_path: str = os.getenv("AGENTGATE_TBOT_IDENTITY", "./.tbot/identity")
    use_mock_executor: bool = os.getenv("AGENTGATE_USE_MOCK_EXECUTOR", "false").lower() == "true"


settings = Settings()
