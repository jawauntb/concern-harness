"""Local LLM adapter — talks to any OpenAI-compatible /v1/chat/completions endpoint.

Works with llama.cpp server, LM Studio, vLLM, Ollama (openai mode), etc.
"""

from __future__ import annotations

import json
from typing import Any

from ..core.schemas import ActionProposal


class LocalLLMAdapter:
    def __init__(
        self,
        name: str,
        url: str,
        model: str = "local",
        api_key: str | None = None,
        temperature: float = 0.0,
        max_tokens: int = 2048,
        timeout: float = 120.0,
        system_prompt: str | None = None,
    ):
        self.name = name
        self.url = url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout
        self.system_prompt = system_prompt or (
            "You are an agent operating inside a load-bearing harness. "
            "You receive a state dict and a ledger dict. Return ONLY a JSON "
            "object that validates against the ActionProposal schema: "
            "{action_id, surface_id, action_type, payload, rationale, claimed_variables_used}. "
            "Do not add commentary."
        )
        self.last_tokens = 0

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
        try:
            import httpx  # type: ignore
        except ImportError as e:
            raise RuntimeError("httpx not installed; pip install httpx") from e

        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        body: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature if temperature is None else temperature,
            "max_tokens": self.max_tokens if max_tokens is None else max_tokens,
        }
        if schema is not None:
            body["response_format"] = {"type": "json_object"}
        if tools:
            body["tools"] = tools

        response = httpx.post(
            f"{self.url}/v1/chat/completions",
            json=body,
            headers=headers,
            timeout=self.timeout,
        )
        response.raise_for_status()
        payload = response.json()
        usage = payload.get("usage") or {}
        self.last_tokens = int(usage.get("total_tokens", 0))
        return payload

    # ------------------------------------------------------------------

    def observe(self, observation: dict) -> None:
        return None

    def propose_action(self, state: dict, ledger: dict) -> ActionProposal:
        user_content = json.dumps({"state": state, "ledger": ledger})
        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": user_content},
        ]
        payload = self.complete(messages, schema={"type": "object"})
        try:
            content = payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as exc:
            return ActionProposal(
                action_id="local_bad_shape",
                surface_id="final_answer",
                action_type="error",
                payload={"error": "unexpected model response", "detail": str(exc), "raw": payload},
            )
        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            return ActionProposal(
                action_id="local_bad_json",
                surface_id="final_answer",
                action_type="error",
                payload={"raw": content},
                rationale="model did not produce valid JSON",
            )
        try:
            return ActionProposal.model_validate(data)
        except Exception as exc:
            return ActionProposal(
                action_id="local_bad_schema",
                surface_id="final_answer",
                action_type="error",
                payload={"raw": data, "error": str(exc)},
            )
