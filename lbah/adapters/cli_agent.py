"""CLI subprocess adapter — round-trip state/ledger via stdin/stdout JSON."""

from __future__ import annotations

import json
import subprocess
from typing import Any

from ..core.schemas import ActionProposal


class CLIAgentAdapter:
    def __init__(
        self,
        name: str,
        command: list[str],
        cwd: str | None = None,
        timeout: float = 120.0,
    ):
        self.name = name
        self.command = command
        self.cwd = cwd
        self.timeout = timeout
        self.last_tokens = 0

    def observe(self, observation: dict) -> None:
        return None

    def propose_action(self, state: dict, ledger: dict) -> ActionProposal:
        payload = {"state": state, "ledger": ledger}
        try:
            proc = subprocess.run(
                self.command,
                input=json.dumps(payload),
                text=True,
                capture_output=True,
                cwd=self.cwd,
                timeout=self.timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            return ActionProposal(
                action_id="cli_timeout",
                surface_id="final_answer",
                action_type="error",
                payload={"error": "timeout", "detail": str(exc)},
                rationale="cli subprocess timed out",
            )

        if proc.returncode != 0:
            return ActionProposal(
                action_id="cli_error",
                surface_id="final_answer",
                action_type="error",
                payload={"stderr": proc.stderr, "returncode": proc.returncode},
                rationale="cli subprocess non-zero exit",
            )

        try:
            data = json.loads(proc.stdout.strip())
        except json.JSONDecodeError as exc:
            return ActionProposal(
                action_id="cli_bad_json",
                surface_id="final_answer",
                action_type="error",
                payload={"stdout": proc.stdout, "error": str(exc)},
                rationale="cli subprocess produced invalid JSON",
            )
        if "_meta" in data and "tokens" in data["_meta"]:
            self.last_tokens = int(data["_meta"]["tokens"])
        return ActionProposal.model_validate(data)
