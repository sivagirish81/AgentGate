"""CLI demo for AgentGate."""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime

import requests


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run an AgentGate demo task.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000", help="AgentGate API base URL")
    parser.add_argument("--task-id", default=f"task-{datetime.utcnow().timestamp():.0f}")
    parser.add_argument("--agent-id", default="agent-demo")
    parser.add_argument("--environment", default="staging", choices=["staging", "prod"])
    parser.add_argument(
        "--task",
        default="Investigate high error rate in staging and restart the deployment if necessary.",
    )
    parser.add_argument("--delegator", default=os.getenv("USER", "human"))
    parser.add_argument("--reason", default="incident remediation")
    parser.add_argument("--ttl", default="1h")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    payload = {
        "task_id": args.task_id,
        "agent_id": args.agent_id,
        "environment": args.environment,
        "natural_language_task": args.task,
        "delegator_user": args.delegator,
        "reason": args.reason,
        "requested_ttl": args.ttl,
    }

    print("Submitting task...")
    response = requests.post(f"{args.base_url}/tasks", json=payload, timeout=10)
    if response.status_code != 200:
        print("Failed to submit task:", response.text)
        return 1

    task = response.json()
    print("Planned actions:")
    print(json.dumps(task["plan"], indent=2))

    if task.get("delegation_required"):
        print("Delegation required. Rendering access request command...")
        request_resp = requests.post(f"{args.base_url}/tasks/{args.task_id}/delegation/request", timeout=10)
        if request_resp.status_code != 200:
            print("Failed to request delegation:", request_resp.text)
            return 1
        request_body = request_resp.json()
        command = request_body.get("teleport_request", {}).get("request_command")
        if command:
            print("Run this command to request access:")
            print(command)
        if os.getenv("AGENTGATE_ACCESS_PROVIDER") == "mock":
            answer = input("Mock approve delegation now? [y/N]: ").strip().lower()
            if answer == "y":
                approve_resp = requests.post(
                    f"{args.base_url}/tasks/{args.task_id}/delegation/approve-mock", timeout=10
                )
                print("Approval response:", approve_resp.json())
            else:
                print("Delegation not approved. Write actions will be blocked.")

    print("Executing task...")
    exec_resp = requests.post(f"{args.base_url}/execute/{args.task_id}", timeout=30)
    if exec_resp.status_code != 200:
        print("Execution failed:", exec_resp.text)
        return 1

    print("Execution results:")
    print(json.dumps(exec_resp.json(), indent=2))

    audit_resp = requests.get(f"{args.base_url}/audit", timeout=10)
    print("Audit trail:")
    print(json.dumps(audit_resp.json(), indent=2))

    return 0


if __name__ == "__main__":
    sys.exit(main())
