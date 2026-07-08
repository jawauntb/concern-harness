"""HTTP-based agent adapter for black-box endpoints."""

from __future__ import annotations

from typing import Any

from ..core.schemas import ActionProposal


class HTTPAgentAdapter:
    def __init__(
        self,
        name: str,
        url: str,
        headers: dict | None = None,
        timeout: float = 120.0,
    ):
        self.name = name
        self.url = url
        self.headers = headers or {}
        self.timeout = timeout
        self.last_tokens = 0

    def observe(self, observation: dict) -> None:
        return None

    def propose_action(self, state: dict, ledger: dict) -> ActionProposal:
        try:
            import httpx  # type: ignore
        except ImportError as e:
            raise RuntimeError("httpx not installed; pip install httpx") from e

        response = httpx.post(
            self.url,
            json={"state": state, "ledger": ledger},
            headers=self.headers,
            timeout=self.timeout,
        )
        response.raise_for_status()
        body = response.json()
        self.last_tokens = int(body.get("_meta", {}).get("tokens", 0))
        return ActionProposal.model_validate(body if "action_id" in body else body["action"])
