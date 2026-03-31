"""CLI demo for AgentGate."""
from __future__ import annotations

import argparse
import json
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
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    payload = {
        "task_id": args.task_id,
        "agent_id": args.agent_id,
        "environment": args.environment,
        "natural_language_task": args.task,
    }

    print("Submitting task...")
    response = requests.post(f"{args.base_url}/tasks", json=payload, timeout=10)
    if response.status_code != 200:
        print("Failed to submit task:", response.text)
        return 1

    task = response.json()
    print("Planned actions:")
    print(json.dumps(task["plan"], indent=2))

    approval_required = task["approval_required"]
    if approval_required:
        answer = input("Approval required. Approve now? [y/N]: ").strip().lower()
        if answer == "y":
            approve_resp = requests.post(f"{args.base_url}/approve/{args.task_id}", timeout=10)
            print("Approval response:", approve_resp.json())
        else:
            reject_resp = requests.post(f"{args.base_url}/reject/{args.task_id}", timeout=10)
            print("Rejected:", reject_resp.json())
            return 0

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
