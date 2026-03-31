"""Teleport-backed infrastructure execution wrappers."""
from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from typing import List

from .config import settings


@dataclass
class CommandResult:
    command: List[str]
    stdout: str
    stderr: str
    returncode: int

    def summary(self, max_lines: int = 20) -> str:
        output = self.stdout.strip() or self.stderr.strip() or "no output"
        lines = output.splitlines()
        return "\n".join(lines[:max_lines])


class TeleportClient:
    """Execute Kubernetes commands using Teleport-issued credentials."""

    def __init__(self) -> None:
        self.kubeconfig_path = settings.tbot_kubeconfig_path

    def _env(self) -> dict:
        env = os.environ.copy()
        env["KUBECONFIG"] = self.kubeconfig_path
        return env

    def _run(self, command: List[str]) -> CommandResult:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            env=self._env(),
            check=False,
        )
        return CommandResult(command, result.stdout, result.stderr, result.returncode)

    def read_pods(self, namespace: str) -> CommandResult:
        return self._run(["kubectl", "get", "pods", "-n", namespace])

    def read_logs(self, namespace: str, deployment: str) -> CommandResult:
        return self._run([
            "kubectl",
            "logs",
            f"deployment/{deployment}",
            "-n",
            namespace,
            "--tail=100",
        ])

    def describe_deployment(self, namespace: str, deployment: str) -> CommandResult:
        return self._run(["kubectl", "describe", "deployment", deployment, "-n", namespace])

    def restart_deployment(self, namespace: str, deployment: str) -> CommandResult:
        return self._run([
            "kubectl",
            "rollout",
            "restart",
            "deployment",
            deployment,
            "-n",
            namespace,
        ])
