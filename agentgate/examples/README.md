# Examples Index

This directory contains minimal, least-privilege examples for running the AgentGate demo.

## Teleport Examples

- `teleport/agentgate-bot-readonly-role.yaml`
  Read-only bot role. Baseline identity for agents.

- `teleport/agentgate-remediator-role.yaml`
  Time-bound remediation role requested via Access Requests.

- `teleport/agentgate-requester-role.yaml`
  Requester role that is allowed to request the remediator role.

- `teleport.yaml`
  General OSS Teleport config template (service stanzas, placeholders).

- `teleport/teleport-oss-local.yaml`
  Local Teleport OSS config with placeholder kubeconfig path.

## Kubernetes RBAC Examples

- `kubernetes/agentgate-readonly-rbac.yaml`
  Read-only permissions for pods and deployments.

- `kubernetes/agentgate-remediator-rbac.yaml`
  Namespaced patch/update permissions for deployments in `default`.

## tbot Config

- `tbot.yaml`
  Example tbot config without static secrets. Uses `${TBOT_TOKEN}` and recommends
  replacing token joins with stronger methods in real deployments.

## OSS vs Enterprise Shape

- OSS-shaped demo uses role requests (`AGENTGATE_TELEPORT_REQUEST_MODE=role`).
- Enterprise-shaped demo uses resource requests (`AGENTGATE_TELEPORT_REQUEST_MODE=resource`).

## Join Method Story

- Local demos can use a short-lived token.
- Real deployments should prefer attested joins: `kubernetes`, `iam`, or CI-based join methods.

## No Static Secrets

No example in this directory includes a committed join token or long-lived credential.
