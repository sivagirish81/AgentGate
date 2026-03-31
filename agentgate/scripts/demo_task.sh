#!/usr/bin/env bash
set -euo pipefail

BASE_URL=${AGENTGATE_URL:-http://127.0.0.1:8000}
TASK_ID=${TASK_ID:-demo-task-$(date +%s)}

curl -sS -X POST "${BASE_URL}/tasks" \
  -H "Content-Type: application/json" \
  -d @- <<JSON
{
  "task_id": "${TASK_ID}",
  "agent_id": "agent-demo",
  "environment": "staging",
  "natural_language_task": "Investigate high error rate in staging and restart the deployment if necessary."
}
JSON

curl -sS -X POST "${BASE_URL}/approve/${TASK_ID}" | cat
curl -sS -X POST "${BASE_URL}/execute/${TASK_ID}" | cat
curl -sS -X GET "${BASE_URL}/audit" | cat
