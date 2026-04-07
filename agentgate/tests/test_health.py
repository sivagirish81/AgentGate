"""Smoke tests for AgentGate."""
from __future__ import annotations

import os

from fastapi.testclient import TestClient

from agentgate.app.db import init_db
from agentgate.app.main import app


def _client() -> TestClient:
    init_db()
    return TestClient(app)


def test_health() -> None:
    with _client() as client:
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
    with _client() as client:
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
    with _client() as client:
        response = client.post("/tasks", json=payload)
    assert response.status_code == 403
