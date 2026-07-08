"""Provider-model adapter for hosted APIs (Anthropic-style).

Lazy-imports the SDK so the harness does not require it unless used.
"""

from __future__ import annotations

import json
import os
from typing import Any

from ..core.schemas import ActionProposal


class ProviderLLMAdapter:
    """Wraps a hosted LLM via the anthropic Python SDK.

    Configure via env var ANTHROPIC_API_KEY, or pass api_key.
    """

    def __init__(
        self,
        name: str,
        model: str = "claude-opus-4-8",
        api_key: str | None = None,
        temperature: float = 0.0,
        max_tokens: int = 2048,
        system_prompt: str | None = None,
    ):
        self.name = name
        self.model = model
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.system_prompt = system_prompt or (
            "You are the actor in a load-bearing agent harness. "
            "Return ONLY a JSON ActionProposal: "
            "{action_id, surface_id, action_type, payload, rationale, claimed_variables_used}."
        )
        self._client = None
        self.last_tokens = 0

    def _get_client(self):
        if self._client is None:
            try:
                import anthropic  # type: ignore
            except ImportError as e:
                raise RuntimeError(
                    "anthropic package not installed; pip install anthropic"
                ) from e
            self._client = anthropic.Anthropic(api_key=self.api_key)
        return self._client

    # ------------------------------------------------------------------

    def complete(
        self,
        messages: list[dict],
        *,
        schema: dict | None = None,
        tools: list[dict] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> dict:
        client = self._get_client()
        system = self.system_prompt
        formatted = []
        for m in messages:
            if m.get("role") == "system":
                system = m["content"]
            else:
                formatted.append(m)
        resp = client.messages.create(
            model=self.model,
            system=system,
            messages=formatted,
            temperature=self.temperature if temperature is None else temperature,
            max_tokens=self.max_tokens if max_tokens is None else max_tokens,
        )
        usage = getattr(resp, "usage", None)
        if usage is not None:
            self.last_tokens = int(getattr(usage, "input_tokens", 0)) + int(
                getattr(usage, "output_tokens", 0)
            )
        text = "".join(
            block.text for block in resp.content if getattr(block, "type", None) == "text"
        )
        return {"choices": [{"message": {"content": text}}], "usage": {"total_tokens": self.last_tokens}}

    # ------------------------------------------------------------------

    def observe(self, observation: dict) -> None:
        return None

    def propose_action(self, state: dict, ledger: dict) -> ActionProposal:
        content = json.dumps({"state": state, "ledger": ledger})
        payload = self.complete(
            [
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": content},
            ],
        )
        text = payload["choices"][0]["message"]["content"].strip()
        # Strip common markdown wrappers.
        if text.startswith("```"):
            text = text.strip("`")
            if text.lower().startswith("json"):
                text = text[4:].strip()
        try:
            data = json.loads(text)
            return ActionProposal.model_validate(data)
        except Exception as exc:
            return ActionProposal(
                action_id="provider_bad",
                surface_id="final_answer",
                action_type="error",
                payload={"raw": text, "error": str(exc)},
            )
