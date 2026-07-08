"""Adapter protocols. Anything that satisfies these can plug into the runner."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from ..core.schemas import ActionProposal


@runtime_checkable
class ModelAdapter(Protocol):
    """A low-level, stateless model interface (chat completion)."""

    name: str

    def complete(
        self,
        messages: list[dict],
        *,
        schema: dict | None = None,
        tools: list[dict] | None = None,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> dict: ...


@runtime_checkable
class AgentAdapter(Protocol):
    """An agent that proposes actions given (state, ledger)."""

    name: str

    def propose_action(self, state: dict, ledger: dict) -> ActionProposal: ...

    def observe(self, observation: dict) -> None: ...
