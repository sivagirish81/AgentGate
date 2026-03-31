"""Smoke tests for AgentGate."""
from __future__ import annotations

import os
import tempfile

# Ensure DB is isolated per test run before app import.
_temp_dir = tempfile.mkdtemp(prefix="agentgate-test-")
os.environ["AGENTGATE_DB_PATH"] = os.path.join(_temp_dir, "agentgate.db")

from fastapi.testclient import TestClient

from agentgate.app.main import app


client = TestClient(app)


def test_health() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_create_task_happy_path() -> None:
    payload = {
        "task_id": "test-task-1",
        "agent_id": "agent-demo",
        "environment": "staging",
        "natural_language_task": "Investigate errors and restart the deployment if necessary.",
    }
    response = client.post("/tasks", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert body["task_id"] == payload["task_id"]
    assert body["agent_id"] == payload["agent_id"]
    assert body["environment"] == payload["environment"]
    assert isinstance(body["plan"], list)


def test_policy_guardrail_denies_disallowed_action() -> None:
    os.environ["AGENTGATE_AGENT_ALLOWLIST"] = (
        '{"agent-readonly":["read_pods","read_logs","describe_deployment"]}'
    )
    payload = {
        "task_id": "test-task-2",
        "agent_id": "agent-readonly",
        "environment": "staging",
        "natural_language_task": "Please restart the deployment now.",
    }
    response = client.post("/tasks", json=payload)
    assert response.status_code == 403
