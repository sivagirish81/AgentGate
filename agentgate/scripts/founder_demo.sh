#!/usr/bin/env bash
set -euo pipefail

BASE_URL=${AGENTGATE_URL:-http://127.0.0.1:8000}
TASK_ID=${TASK_ID:-founder-demo-$(date +%s)}
AGENT_ID=${AGENT_ID:-agent-demo}
ENVIRONMENT=${ENVIRONMENT:-staging}
DELEGATOR=${DELEGATOR:-demo-user}
REASON=${REASON:-founder demo}
TTL=${TTL:-1h}
REQUEST_MODE=${REQUEST_MODE:-${AGENTGATE_TELEPORT_REQUEST_MODE:-role}}
TELEPORT_REQUEST_ID=${TELEPORT_REQUEST_ID:-}
TASK_TEXT=${TASK_TEXT:-"Investigate errors and restart the deployment my-app if needed."}

JSON_PRINTER="python -m json.tool"
if command -v jq >/dev/null 2>&1; then
  JSON_PRINTER="jq"
fi

banner() {
  printf "\n== %s ==\n" "$1"
}

fail() {
  echo "[error] $1" >&2
  exit 1
}

banner "Checking API"
if ! curl -sS "${BASE_URL}/health" >/dev/null; then
  fail "AgentGate API not reachable at ${BASE_URL}. Start the server first."
fi

task_payload=$(cat <<JSON
{
  "task_id": "${TASK_ID}",
  "agent_id": "${AGENT_ID}",
  "environment": "${ENVIRONMENT}",
  "natural_language_task": "${TASK_TEXT}",
  "delegator_user": "${DELEGATOR}",
  "reason": "${REASON}",
  "requested_ttl": "${TTL}",
  "request_mode": "${REQUEST_MODE}"
}
JSON
)

banner "Create task"
create_resp=$(curl -sS -X POST "${BASE_URL}/tasks" -H "Content-Type: application/json" -d "${task_payload}")
printf "%s" "$create_resp" | eval "$JSON_PRINTER"

delegation_required=$(printf "%s" "$create_resp" | python -c 'import json,sys; print(json.load(sys.stdin).get("delegation_required", False))')

banner "Inspect plan"
printf "%s" "$create_resp" | python -c 'import json,sys; print(json.dumps(json.load(sys.stdin)["plan"], indent=2))'

if [[ "$delegation_required" == "True" ]]; then
  banner "Request delegation"
  request_resp=$(curl -sS -X POST "${BASE_URL}/tasks/${TASK_ID}/delegation/request")
  printf "%s" "$request_resp" | eval "$JSON_PRINTER"
  request_command=$(printf "%s" "$request_resp" | python -c 'import json,sys; print(json.load(sys.stdin).get("teleport_request", {}).get("request_command", ""))')
  if [[ -n "$request_command" ]]; then
    echo
    echo "Teleport access request command:"
    echo "$request_command"
  fi
  if [[ -n "$TELEPORT_REQUEST_ID" ]]; then
    echo
    echo "Attaching Teleport request id ${TELEPORT_REQUEST_ID} to delegation session..."
    attach_resp=$(curl -sS -X POST "${BASE_URL}/tasks/${TASK_ID}/delegation/attach" \
      -H "Content-Type: application/json" \
      -d "{\"teleport_request_id\": \"${TELEPORT_REQUEST_ID}\"}")
    printf "%s" "$attach_resp" | eval "$JSON_PRINTER"
  else
    echo
    echo "Tip: set TELEPORT_REQUEST_ID to enable auth-api refresh (example: TELEPORT_REQUEST_ID=<id> ./agentgate/scripts/founder_demo.sh)"
  fi
  if [[ "${AGENTGATE_ACCESS_PROVIDER:-}" == "mock" ]]; then
    banner "Mock approval"
    approve_resp=$(curl -sS -X POST "${BASE_URL}/tasks/${TASK_ID}/delegation/approve-mock")
    printf "%s" "$approve_resp" | eval "$JSON_PRINTER"
  else
    echo
    echo "Approval is real Teleport workflow. Approve the request in Teleport before executing."
  fi
else
  echo "No delegation required. Proceeding to execution."
fi

banner "Execute"
exec_resp=$(curl -sS -X POST "${BASE_URL}/execute/${TASK_ID}")
printf "%s" "$exec_resp" | eval "$JSON_PRINTER"

banner "Final task state"
final_resp=$(curl -sS "${BASE_URL}/tasks/${TASK_ID}")
printf "%s" "$final_resp" | eval "$JSON_PRINTER"

banner "Audit (latest)"
audit_resp=$(curl -sS "${BASE_URL}/audit")
printf "%s" "$audit_resp" | eval "$JSON_PRINTER"

banner "Summary"
if [[ "${AGENTGATE_ACCESS_PROVIDER:-}" == "mock" ]]; then
  echo "Run type: fully simulated (mock provider + mock executor)"
elif [[ -n "${AGENTGATE_ELEVATED_KUBECONFIG:-}" ]]; then
  echo "Run type: Teleport command rendered; elevated execution enabled"
else
  echo "Run type: Teleport command rendered; write actions blocked without elevated kubeconfig"
fi

echo "Delegation required: ${delegation_required}"
