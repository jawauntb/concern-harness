"""Coding agents for deterministic tests, demos, and model-backed runs."""

from __future__ import annotations

import json
from typing import Any

from ..adapters.base import ModelAdapter
from ..adapters.external_harness import extract_first_json_object
from .actions import CodingAction


class ScriptedCodingAgent:
    """Returns a fixed sequence of coding actions.

    This is not meant to be competitive. It gives tests, docs, and benchmark
    harness smoke runs a deterministic agent while model-backed coding agents
    can implement the same ``propose_action``/``observe`` pair.
    """

    def __init__(self, actions: list[CodingAction], name: str = "scripted_coder"):
        self.name = name
        self.actions = list(actions)
        self.observations: list[dict] = []
        self.last_tokens = 0
        self._index = 0

    def propose_action(self, state: dict, ledger: dict) -> CodingAction:
        if self._index >= len(self.actions):
            return CodingAction(
                action_id=f"{self.name}_finish_{self._index}",
                action_type="finish",
                rationale="script exhausted",
            )
        action = self.actions[self._index]
        self._index += 1
        return action

    def observe(self, observation: dict) -> None:
        self.observations.append(observation)


ACTION_SCHEMA_HINT = {
    "type": "object",
    "properties": {
        "action_id": {"type": "string"},
        "action_type": {
            "type": "string",
            "enum": [
                "inspect",
                "search",
                "read_file",
                "edit_file",
                "run_command",
                "run_tests",
                "finish",
            ],
        },
        "payload": {"type": "object"},
        "rationale": {"type": "string"},
        "concerns_addressed": {"type": "array", "items": {"type": "string"}},
        "ledger_updates": {"type": "array", "items": {"type": "object"}},
    },
    "required": ["action_type"],
}


MODEL_CODING_SYSTEM_PROMPT = """You are an LBAH-Code coding agent.

You control a real repository through typed actions. Return exactly one JSON
object and no prose. Valid actions:

- inspect: summarize workspace state; payload {}
- search: find text; payload {"pattern": "...", "glob": "*.py", "limit": 50}
- read_file: read a file; payload {"path": "file.py", "start": 1, "limit": 200}
- edit_file: edit source; payload {"path": "file.py", "old": "...", "new": "..."}
  or {"path": "file.py", "content": "..."}
- run_command: run a command; payload {"command": ["python", "-m", "pytest", "-q"]}
- run_tests: run configured tests; payload {} or {"commands": [[...]]}
- finish: request verification; payload {}

Use the ledger. Address concerns when your action supplies evidence for them.
When verification fails, inspect the failure and try a new action instead of
repeating the same unsuccessful edit.
"""


RAW_CODING_SYSTEM_PROMPT = """You are a coding agent.

You control a real repository through typed actions. Return exactly one JSON
object and no prose. Valid actions:

- inspect: summarize workspace state; payload {}
- search: find text; payload {"pattern": "...", "glob": "*.py", "limit": 50}
- read_file: read a file; payload {"path": "file.py", "start": 1, "limit": 200}
- edit_file: edit source; payload {"path": "file.py", "old": "...", "new": "..."}
  or {"path": "file.py", "content": "..."}
- run_command: run a command; payload {"command": ["python", "-m", "pytest", "-q"]}
- run_tests: run configured tests; payload {} or {"commands": [[...]]}
- finish: request verification; payload {}

Solve the issue from the problem statement. Prefer reading and editing source
files directly. When verification fails, inspect the failure and try a new
action instead of repeating the same unsuccessful edit.
"""


def extract_action_json(text: str) -> dict[str, Any]:
    """Extract the first JSON object from model text."""
    return extract_first_json_object(text)


def model_response_content(response: dict[str, Any]) -> str:
    """Normalize common chat-completion response shapes to text."""
    if isinstance(response.get("content"), str):
        return response["content"]
    if isinstance(response.get("text"), str):
        return response["text"]
    choices = response.get("choices")
    if isinstance(choices, list) and choices:
        first = choices[0]
        if isinstance(first, dict):
            message = first.get("message")
            if isinstance(message, dict):
                content = message.get("content")
                if isinstance(content, str):
                    return content
                if isinstance(content, list):
                    parts: list[str] = []
                    for part in content:
                        if isinstance(part, dict):
                            parts.append(str(part.get("text", "")))
                        elif isinstance(part, str):
                            parts.append(part)
                    return "\n".join(parts)
            text = first.get("text")
            if isinstance(text, str):
                return text
    if isinstance(response.get("output_text"), str):
        return response["output_text"]
    raise ValueError("model response did not include text content")


class ModelCodingAgent:
    """Model-backed agent that emits typed LBAH-Code actions."""

    def __init__(
        self,
        model: ModelAdapter,
        name: str | None = None,
        *,
        system_prompt: str = MODEL_CODING_SYSTEM_PROMPT,
        temperature: float = 0.0,
        max_tokens: int = 2048,
    ):
        self.model = model
        self.name = name or f"{model.name}_coding"
        self.system_prompt = system_prompt
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.observations: list[dict[str, Any]] = []
        self.last_tokens = 0

    def propose_action(self, state: dict, ledger: dict) -> CodingAction:
        response = self.model.complete(
            [
                {"role": "system", "content": self.system_prompt},
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "state": state,
                            "ledger": ledger,
                            "recent_observations": self.observations[-5:],
                        },
                        indent=2,
                    ),
                },
            ],
            schema=ACTION_SCHEMA_HINT,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
        )
        self.last_tokens = int(
            response.get("usage", {}).get("total_tokens", 0)
            or getattr(self.model, "last_tokens", 0)
            or 0
        )
        data = extract_action_json(model_response_content(response))
        data.setdefault("action_id", f"{self.name}_{state.get('step', 0)}")
        data.setdefault("payload", {})
        return CodingAction.model_validate(data)

    def observe(self, observation: dict) -> None:
        self.observations.append(observation)
