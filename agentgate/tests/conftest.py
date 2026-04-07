"""Shared test configuration for AgentGate."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path
import sys

_temp_dir = tempfile.mkdtemp(prefix="agentgate-tests-")
os.environ.setdefault("AGENTGATE_DB_PATH", os.path.join(_temp_dir, "agentgate.db"))
os.environ.setdefault("AGENTGATE_ACCESS_PROVIDER", "mock")
os.environ.setdefault("AGENTGATE_USE_MOCK_EXECUTOR", "true")
os.environ.setdefault("AGENTGATE_TELEPORT_REQUEST_MODE", "role")
os.environ.setdefault("AGENTGATE_TELEPORT_REQUEST_ROLE", "agentgate-remediator")
os.environ.setdefault("AGENTGATE_TELEPORT_CLUSTER", "agentgate-local")
os.environ.setdefault("AGENTGATE_TELEPORT_KUBE_CLUSTER", "kind-agentgate")

repo_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(repo_root))
