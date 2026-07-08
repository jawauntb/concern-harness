"""Adapter that uses the `claude -p` CLI as an LLM backend.

Handy when there is no ANTHROPIC_API_KEY in the environment but a Claude Code
session is available on the host. Each `propose_action` shells out to a fresh
`claude -p` non-interactive call.
"""

from __future__ import annotations

import json
import re
import subprocess
from typing import Any

from ..core.schemas import ActionProposal


SYSTEM_PROMPT = (
    "You are the actor inside a Load-Bearing Agent Harness. Return ONLY a JSON "
    "ActionProposal, no prose, no code fences: "
    "{action_id, surface_id, action_type, payload, rationale, claimed_variables_used}."
)


def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```\s*$", "", text)
    return text.strip()


class ClaudeCodeCLIAdapter:
    """Uses `claude -p` for one-shot LLM calls."""

    def __init__(
        self,
        name: str = "claude_opus_4_7",
        model: str = "claude-opus-4-7",
        timeout: float = 90.0,
        extra_args: list[str] | None = None,
        system_prompt: str | None = None,
    ):
        self.name = name
        self.model = model
        self.timeout = timeout
        self.extra_args = extra_args or []
        self.system_prompt = system_prompt or SYSTEM_PROMPT
        self.last_tokens = 0

    # ------------------------------------------------------------------

    def _call(self, prompt: str) -> str:
        cmd = [
            "claude",
            "-p",
            "--model",
            self.model,
            "--output-format",
            "text",
            "--append-system-prompt",
            self.system_prompt,
            *self.extra_args,
            prompt,
        ]
        try:
            proc = subprocess.run(
                cmd,
                text=True,
                capture_output=True,
                timeout=self.timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            return json.dumps(
                {
                    "action_id": "claude_timeout",
                    "surface_id": "final_answer",
                    "action_type": "error",
                    "payload": {"error": "timeout", "detail": str(exc)},
                }
            )
        if proc.returncode != 0:
            return json.dumps(
                {
                    "action_id": "claude_error",
                    "surface_id": "final_answer",
                    "action_type": "error",
                    "payload": {"stderr": proc.stderr[-500:], "returncode": proc.returncode},
                }
            )
        return proc.stdout

    # ------------------------------------------------------------------

    def observe(self, observation: dict) -> None:
        return None

    def propose_action(self, state: dict, ledger: dict) -> ActionProposal:
        prompt = (
            "Below is the current STATE and CONCERN LEDGER for a load-bearing agent "
            "harness. Emit a single JSON ActionProposal object. High-concern variables "
            "(concern >= 0.7) MUST appear in payload. Variables with proxy_risks that "
            "include 'forbidden' MUST NOT appear. Variables with freshness < 0.5 are "
            "stale and require a `recheck` action first. Return JSON only.\n\n"
            f"STATE:\n{json.dumps(state)}\n\nLEDGER:\n{json.dumps(ledger)}"
        )
        raw = self._call(prompt)
        text = _strip_fences(raw)
        try:
            data = json.loads(text)
            return ActionProposal.model_validate(data)
        except Exception as exc:
            return ActionProposal(
                action_id="claude_bad_json",
                surface_id="final_answer",
                action_type="error",
                payload={"raw": text[:1500], "error": str(exc)},
                rationale="claude CLI returned non-parseable JSON",
            )
