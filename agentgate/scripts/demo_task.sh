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
  "natural_language_task": "Investigate high error rate in staging and restart the deployment if necessary.",
  "delegator_user": "demo-user",
  "reason": "demo remediation",
  "requested_ttl": "1h"
}
JSON

echo "Rendering delegation request..."
curl -sS -X POST "${BASE_URL}/tasks/${TASK_ID}/delegation/request" | cat

if [[ "${AGENTGATE_ACCESS_PROVIDER:-}" == "mock" ]]; then
  echo "Mock approving delegation..."
  curl -sS -X POST "${BASE_URL}/tasks/${TASK_ID}/delegation/approve-mock" | cat
fi

echo "Executing task..."
curl -sS -X POST "${BASE_URL}/execute/${TASK_ID}" | cat

echo "Audit trail:"
curl -sS -X GET "${BASE_URL}/audit" | cat
