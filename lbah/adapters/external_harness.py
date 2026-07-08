"""Adapters for black-box agent harnesses.

These adapters are intentionally conservative: they treat systems such as
Fugu, OpenHands servers, or an internal agent service as opaque workers that
must return an LBAH `ActionProposal`. LBAH remains the measurement and gating
layer around them.
"""

from __future__ import annotations

import json
from typing import Any

from ..core.schemas import ActionProposal


ACTION_SCHEMA_HINT = {
    "action_id": "stable id for this proposed action",
    "surface_id": "commitment surface id from the ledger",
    "action_type": "tool/action/final-answer type",
    "payload": "JSON object that will be committed to the environment",
    "rationale": "short reason for the action",
    "claimed_variables_used": "list of concern variable ids used",
}


def _strip_fence(text: str) -> str:
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    lines = stripped.splitlines()
    if len(lines) >= 2 and lines[-1].strip() == "```":
        return "\n".join(lines[1:-1]).strip()
    return stripped


def extract_first_json_object(text: str) -> dict[str, Any]:
    """Return the first JSON object embedded in a model response."""
    text = _strip_fence(text)
    decoder = json.JSONDecoder()
    for idx, ch in enumerate(text):
        if ch != "{":
            continue
        try:
            parsed, _ = decoder.raw_decode(text[idx:])
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    raise ValueError("response did not contain a JSON object")


def _first_surface_id(ledger: dict) -> str:
    surfaces = ledger.get("surfaces") or []
    if surfaces:
        return str(surfaces[0].get("id") or surfaces[0].get("type") or "final_answer")
    return "final_answer"


def normalize_action_dict(data: dict[str, Any], ledger: dict) -> dict[str, Any]:
    """Coerce common agent response shapes into an ActionProposal dict."""
    if "action" in data and isinstance(data["action"], dict):
        data = data["action"]

    control_keys = {
        "action_id",
        "surface_id",
        "action_type",
        "payload",
        "rationale",
        "claimed_variables_used",
    }
    metadata = (ledger.get("task") or {}).get("metadata") or {}
    out = dict(data)
    out.setdefault("action_id", "external_action")
    out.setdefault("surface_id", _first_surface_id(ledger))
    out.setdefault("action_type", metadata.get("expected_action_type", "answer"))
    if "payload" not in out:
        payload = {k: v for k, v in data.items() if k not in control_keys}
        if not payload and "answer" in data:
            payload = {"answer": data["answer"]}
        out["payload"] = payload
    out.setdefault("rationale", None)
    out.setdefault("claimed_variables_used", [])
    return out


def _content_from_openai_body(body: dict[str, Any]) -> str:
    """Extract text from common Chat Completions and Responses bodies."""
    if "choices" in body:
        message = body["choices"][0].get("message") or {}
        content = message.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return "\n".join(
                str(part.get("text", ""))
                for part in content
                if isinstance(part, dict)
            )
    if isinstance(body.get("output_text"), str):
        return body["output_text"]
    if isinstance(body.get("text"), str):
        return body["text"]
    if isinstance(body.get("response"), str):
        return body["response"]
    return json.dumps(body)


class OpenAICompatibleHarnessAdapter:
    """Call an OpenAI-compatible model or multi-agent harness as an AgentAdapter.

    The default endpoint works with Chat Completions-compatible APIs. The model
    may be a single LLM or a learned orchestrator exposed through one endpoint.
    """

    def __init__(
        self,
        name: str,
        base_url: str,
        model: str,
        api_key: str | None = None,
        endpoint_path: str = "/v1/chat/completions",
        headers: dict[str, str] | None = None,
        timeout: float = 300.0,
        temperature: float = 0.0,
        max_tokens: int = 4096,
        system_prompt: str | None = None,
    ):
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.endpoint_path = endpoint_path
        self.headers = headers or {}
        self.timeout = timeout
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.system_prompt = system_prompt or (
            "You are running inside LBAH, a load-bearing agent harness. "
            "Return only JSON matching this action schema: "
            f"{json.dumps(ACTION_SCHEMA_HINT, sort_keys=True)}."
        )
        self.last_tokens = 0

    def observe(self, observation: dict) -> None:
        return None

    def _headers(self) -> dict[str, str]:
        headers = {"content-type": "application/json", **self.headers}
        if self.api_key:
            headers.setdefault("authorization", f"Bearer {self.api_key}")
        return headers

    def _body(self, state: dict, ledger: dict) -> dict[str, Any]:
        user_payload = {
            "state": state,
            "ledger": ledger,
            "required_action_schema": ACTION_SCHEMA_HINT,
        }
        return {
            "model": self.model,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "messages": [
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": json.dumps(user_payload, default=str)},
            ],
        }

    def propose_action(self, state: dict, ledger: dict) -> ActionProposal:
        try:
            import httpx  # type: ignore
        except ImportError as e:
            raise RuntimeError("httpx not installed; pip install httpx") from e

        response = httpx.post(
            f"{self.base_url}{self.endpoint_path}",
            headers=self._headers(),
            json=self._body(state, ledger),
            timeout=self.timeout,
        )
        response.raise_for_status()
        body = response.json()
        usage = body.get("usage") or {}
        self.last_tokens = int(
            usage.get("total_tokens")
            or usage.get("output_tokens")
            or body.get("_meta", {}).get("tokens", 0)
        )
        if "action_id" in body or "action" in body:
            action = normalize_action_dict(body, ledger)
        else:
            action = normalize_action_dict(
                extract_first_json_object(_content_from_openai_body(body)),
                ledger,
            )
        return ActionProposal.model_validate(action)
