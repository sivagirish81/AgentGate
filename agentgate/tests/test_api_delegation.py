"""API tests for delegation-driven flows."""
from __future__ import annotations

from fastapi.testclient import TestClient

from agentgate.app.db import init_db
from agentgate.app.main import app


def _client() -> TestClient:
    init_db()
    return TestClient(app)


def test_read_only_task_executes_without_delegation() -> None:
    payload = {
        "task_id": "read-task",
        "agent_id": "agent-demo",
        "environment": "staging",
        "natural_language_task": "Check pods in the cluster.",
    }
    with _client() as client:
        response = client.post("/tasks", json=payload)
        assert response.status_code == 200
        body = response.json()
        assert body["delegation_required"] is False
        execute = client.post(f"/execute/{payload['task_id']}")
        assert execute.status_code == 200
        results = execute.json()["results"]
        assert results[0]["status"] == "success"


def test_write_task_requires_delegation() -> None:
    payload = {
        "task_id": "write-task",
        "agent_id": "agent-demo",
        "environment": "staging",
        "natural_language_task": "Restart deployment my-app.",
    }
    with _client() as client:
        response = client.post("/tasks", json=payload)
        assert response.status_code == 200
        body = response.json()
        assert body["delegation_required"] is True
        request = client.post(f"/tasks/{payload['task_id']}/delegation/request")
        assert request.status_code == 200
        req_body = request.json()
        assert req_body["teleport_request"]["request_command"]
        execute = client.post(f"/execute/{payload['task_id']}")
        assert execute.status_code == 200
        results = execute.json()["results"]
        assert results[-1]["status"] == "blocked"


def test_mock_approval_allows_execution() -> None:
    payload = {
        "task_id": "write-task-approve",
        "agent_id": "agent-demo",
        "environment": "staging",
        "natural_language_task": "Restart deployment my-app.",
        "delegator_user": "alice",
    }
    with _client() as client:
        response = client.post("/tasks", json=payload)
        assert response.status_code == 200
        request = client.post(f"/tasks/{payload['task_id']}/delegation/request")
        assert request.status_code == 200
        approve = client.post(f"/tasks/{payload['task_id']}/delegation/approve-mock")
        assert approve.status_code == 200
        execute = client.post(f"/execute/{payload['task_id']}")
        assert execute.status_code == 200
        results = execute.json()["results"]
        assert results[-1]["status"] == "success"


def test_revocation_blocks_execution() -> None:
    payload = {
        "task_id": "write-task-revoke",
        "agent_id": "agent-demo",
        "environment": "staging",
        "natural_language_task": "Restart deployment my-app.",
    }
    with _client() as client:
        client.post("/tasks", json=payload)
        client.post(f"/tasks/{payload['task_id']}/delegation/request")
        client.post(f"/tasks/{payload['task_id']}/delegation/approve-mock")
        revoke = client.post(f"/tasks/{payload['task_id']}/delegation/revoke")
        assert revoke.status_code == 200
        execute = client.post(f"/execute/{payload['task_id']}")
        results = execute.json()["results"]
        assert results[-1]["status"] == "blocked"


def test_audit_includes_delegation_metadata() -> None:
    payload = {
        "task_id": "audit-task",
        "agent_id": "agent-demo",
        "environment": "staging",
        "natural_language_task": "Restart deployment my-app.",
        "delegator_user": "alice",
    }
    with _client() as client:
        client.post("/tasks", json=payload)
        client.post(f"/tasks/{payload['task_id']}/delegation/request")
        audit = client.get("/audit")
        assert audit.status_code == 200
        events = audit.json()
        assert events
        assert events[0]["delegation_session_id"]
        assert events[0]["requested_scope_json"] is not None
