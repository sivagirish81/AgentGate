#!/usr/bin/env bash
set -euo pipefail

if [[ -f ".env" ]]; then
  # shellcheck disable=SC1091
  source ".env"
fi

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
AUTO_REFRESH=${AUTO_REFRESH:-true}
WAIT_FOR_APPROVAL=${WAIT_FOR_APPROVAL:-false}
WAIT_TIMEOUT_SECONDS=${WAIT_TIMEOUT_SECONDS:-120}
WAIT_INTERVAL_SECONDS=${WAIT_INTERVAL_SECONDS:-5}
PROMPT_FOR_REQUEST_ID=${PROMPT_FOR_REQUEST_ID:-true}
AUTO_CREATE_REQUEST=${AUTO_CREATE_REQUEST:-false}
TCTL_AUTH_SERVER=${TCTL_AUTH_SERVER:-127.0.0.1:3025}
TCTL_CONFIG=${TCTL_CONFIG:-/Users/sivagirish/Documents/Work/Project/AgentGate/agentgate/examples/teleport/teleport-oss-local.yaml}
TBOT_KUBECONFIG=${AGENTGATE_TBOT_KUBECONFIG:-./.tbot-output/kubeconfig.yaml}
ELEVATED_KUBECONFIG=${AGENTGATE_ELEVATED_KUBECONFIG:-}
SKIP_PREFLIGHT=${SKIP_PREFLIGHT:-false}

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

banner "Preflight (read-only identity)"
if [[ "${SKIP_PREFLIGHT}" == "true" ]]; then
  echo "Preflight skipped (SKIP_PREFLIGHT=true)."
else
  if [[ ! -f "${TBOT_KUBECONFIG}" ]]; then
    fail "tbot kubeconfig not found at ${TBOT_KUBECONFIG}. Start tbot or set AGENTGATE_TBOT_KUBECONFIG."
  fi
  echo "Using tbot kubeconfig: ${TBOT_KUBECONFIG}"
  if ! kubectl --kubeconfig "${TBOT_KUBECONFIG}" --request-timeout=5s auth can-i get pods -n default >/dev/null 2>&1; then
    fail "tbot kubeconfig cannot reach the cluster. Ensure Teleport kube proxy is running and tbot is healthy."
  fi
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
    echo "Human step: open a Teleport access request in another terminal:"
    echo "  $request_command"
    if [[ -n "${AGENTGATE_TELEPORT_PROXY:-}" ]]; then
      echo
      echo "If you need an explicit proxy flag, use:"
      echo "  ${request_command} --proxy=${AGENTGATE_TELEPORT_PROXY} --insecure"
    else
      echo
      echo "If your proxy is local, use:"
      echo "  ${request_command} --proxy=127.0.0.1:3080 --insecure"
    fi
    if echo "$request_command" | grep -q -- '--ttl="1h"'; then
      echo
      echo "Note: tsh expects minutes for --ttl. Equivalent command:"
      echo "  ${request_command/--ttl=\"1h\"/--ttl=60}"
    fi
    echo
    echo "Conversation note: this demo requires an explicit approval step (OSS Teleport has no UI)."
    echo "Task id (AgentGate): ${TASK_ID}"
    echo "When the request is created, copy the Request ID and run:"
    echo "  tctl --auth-server=${TCTL_AUTH_SERVER} --config=${TCTL_CONFIG} requests approve <request-id> --reason=\"${REASON}\""
    echo
    echo "Then attach it to the task so the demo can continue:"
    echo "  curl -s -X POST ${BASE_URL}/tasks/${TASK_ID}/delegation/attach \\"
    echo "    -H \"Content-Type: application/json\" \\"
    echo "    -d '{\"teleport_request_id\":\"<request-id>\"}'"
    echo
    echo "And refresh the task status:"
    echo "  curl -s -X POST ${BASE_URL}/tasks/${TASK_ID}/delegation/refresh"
  fi
  if [[ "${AUTO_CREATE_REQUEST}" == "true" && -n "$request_command" ]]; then
    echo
    echo "Agent step: creating the Teleport access request automatically..."
    tsh_parts=()
    while IFS= read -r line; do
      tsh_parts+=("$line")
    done < <(python -c 'import shlex,sys; print("\n".join(shlex.split(sys.argv[1])))' "$request_command")
    if [[ -n "${AGENTGATE_TELEPORT_PROXY:-}" ]]; then
      tsh_parts+=("--proxy=${AGENTGATE_TELEPORT_PROXY}" "--insecure" "--nowait")
    else
      tsh_parts+=("--proxy=127.0.0.1:3080" "--insecure" "--nowait")
    fi
    if printf '%s\n' "${tsh_parts[@]}" | grep -q -- '--ttl=1h'; then
      for i in "${!tsh_parts[@]}"; do
        if [[ "${tsh_parts[$i]}" == "--ttl=1h" ]]; then
          tsh_parts[$i]="--ttl=60"
        fi
      done
    fi
    tsh_out="$("${tsh_parts[@]}" 2>&1 || true)"
    if echo "$tsh_out" | grep -q "ssh: cert has expired"; then
      echo "$tsh_out"
      fail "Teleport cert expired. Run: tsh login --proxy=127.0.0.1:3080 --insecure"
    fi
    if ! echo "$tsh_out" | grep -q "Request ID"; then
      echo "$tsh_out"
      fail "Failed to create request with tsh. See output above."
    fi
    TELEPORT_REQUEST_ID=$(echo "$tsh_out" | awk -F':' '/Request ID/{gsub(/^[ \t]+/,"",$2); gsub(/[ \t]+$/,"",$2); print $2; exit}')
    echo "$tsh_out"
    echo
    echo "Created request id: ${TELEPORT_REQUEST_ID}"
  fi
  if [[ -z "$TELEPORT_REQUEST_ID" && "${WAIT_FOR_APPROVAL}" == "true" && "${PROMPT_FOR_REQUEST_ID}" == "true" ]]; then
    if [[ -t 0 ]]; then
      echo
      echo "Paste the Teleport Request ID from the other terminal, then press Enter."
      read -r -p "Request ID: " TELEPORT_REQUEST_ID
    else
      echo
      echo "Note: stdin is not interactive; cannot prompt for Request ID."
    fi
  fi
  if [[ -n "$TELEPORT_REQUEST_ID" ]]; then
    echo
    echo "Agent step: attaching Teleport request id ${TELEPORT_REQUEST_ID} to the delegation session..."
    attach_resp=$(curl -sS -X POST "${BASE_URL}/tasks/${TASK_ID}/delegation/attach" \
      -H "Content-Type: application/json" \
      -d "{\"teleport_request_id\": \"${TELEPORT_REQUEST_ID}\"}")
    printf "%s" "$attach_resp" | eval "$JSON_PRINTER"
    echo
    echo "Human step (OSS Teleport): approve the request in another terminal:"
    echo "  tctl --auth-server=${TCTL_AUTH_SERVER} --config=${TCTL_CONFIG} requests approve ${TELEPORT_REQUEST_ID} --reason=\"${REASON}\""
    echo
    echo "Human step: refresh the task after approval:"
    echo "  curl -s -X POST ${BASE_URL}/tasks/${TASK_ID}/delegation/refresh"
    if [[ "${AGENTGATE_ACCESS_PROVIDER:-}" == "auth_api" && "${AUTO_REFRESH}" == "true" ]]; then
      banner "Refresh delegation status"
      refresh_resp=$(curl -sS -X POST "${BASE_URL}/tasks/${TASK_ID}/delegation/refresh")
      printf "%s" "$refresh_resp" | eval "$JSON_PRINTER"
    fi
    if [[ "${WAIT_FOR_APPROVAL}" == "true" ]]; then
      echo
      echo "Waiting for approval (up to ${WAIT_TIMEOUT_SECONDS}s)..."
      start_ts=$(date +%s)
      while true; do
        status_resp=$(curl -sS "${BASE_URL}/tasks/${TASK_ID}/delegation")
        delegation_status=$(printf "%s" "$status_resp" | python -c 'import json,sys; print((json.load(sys.stdin).get("delegation_session") or {}).get("status", ""))')
        if [[ "$delegation_status" == "approved" ]]; then
          echo "Approved."
          break
        fi
        now_ts=$(date +%s)
        elapsed=$((now_ts - start_ts))
        if (( elapsed >= WAIT_TIMEOUT_SECONDS )); then
          echo "Timed out waiting for approval (status=${delegation_status})."
          break
        fi
        sleep "${WAIT_INTERVAL_SECONDS}"
      done
    fi
  else
    echo
    echo "Human step: after you run the request command, re-run this script with TELEPORT_REQUEST_ID set."
    echo "Example: TELEPORT_REQUEST_ID=<id> ./agentgate/scripts/founder_demo.sh"
    if [[ "${WAIT_FOR_APPROVAL}" == "true" ]]; then
      echo
      echo "Note: WAIT_FOR_APPROVAL=true requires TELEPORT_REQUEST_ID to poll approval."
    fi
  fi
  if [[ "${AGENTGATE_ACCESS_PROVIDER:-}" == "mock" ]]; then
    banner "Mock approval"
    approve_resp=$(curl -sS -X POST "${BASE_URL}/tasks/${TASK_ID}/delegation/approve-mock")
    printf "%s" "$approve_resp" | eval "$JSON_PRINTER"
  else
    echo
    echo "Human step: approve the request in Teleport (UI or tctl)."
  fi
else
  echo "No delegation required. Proceeding to execution."
fi

if [[ "${AGENTGATE_ACCESS_PROVIDER:-}" != "mock" && -z "${ELEVATED_KUBECONFIG}" ]]; then
  echo
  echo "Human step: set AGENTGATE_ELEVATED_KUBECONFIG and restart the API to enable write actions."
fi

should_execute=true
if [[ "$delegation_required" == "True" ]]; then
  status_resp=$(curl -sS "${BASE_URL}/tasks/${TASK_ID}/delegation")
  delegation_status=$(printf "%s" "$status_resp" | python -c 'import json,sys; print((json.load(sys.stdin).get("delegation_session") or {}).get("status", ""))')
  if [[ "$delegation_status" != "approved" ]]; then
    should_execute=false
    echo
    echo "Skipping execution: delegation not approved yet (status=${delegation_status})."
    echo "Human step: approve in Teleport, then refresh:"
    echo "  curl -s -X POST ${BASE_URL}/tasks/${TASK_ID}/delegation/refresh"
  fi
  if [[ -z "${ELEVATED_KUBECONFIG}" ]]; then
    should_execute=false
    echo
    echo "Skipping execution: AGENTGATE_ELEVATED_KUBECONFIG not set."
  fi
fi

if [[ "${should_execute}" == "true" ]]; then
  banner "Execute"
  exec_resp=$(curl -sS -X POST "${BASE_URL}/execute/${TASK_ID}")
  printf "%s" "$exec_resp" | eval "$JSON_PRINTER"
else
  banner "Execute"
  echo "Execution skipped."
fi

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
