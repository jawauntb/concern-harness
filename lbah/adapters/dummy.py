"""Dummy adapters used for tests, benchmarks, and reproducible baselines.

- `DummyAgent`: proposes actions from simple deterministic policies. Configurable
  policies let benchmarks compare a proxy-prone agent, a random agent, and an
  oracle without touching real models.

- `EchoModel`: a stand-in `ModelAdapter` for LLM-backed modules; useful when you
  want to run modules without external services (returns pre-canned JSON).
"""

from __future__ import annotations

import random
from typing import Any

from ..core.schemas import ActionProposal


class EchoModel:
    """Model adapter that returns a canned response. Useful as a placeholder."""

    def __init__(self, name: str = "echo", canned: dict | None = None):
        self.name = name
        self.canned = canned or {"content": "{}"}

    def complete(
        self,
        messages: list[dict],
        *,
        schema: dict | None = None,
        tools: list[dict] | None = None,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> dict:
        return dict(self.canned)


class DummyAgent:
    """Proxy-prone deterministic agent for baselines.

    Policies:
      - "first_slot": use the first field of a 4-field prompt
      - "last_slot": use the last field of a 4-field prompt
      - "random_slot": choose a random field (seeded)
      - "constant": always answer with a fixed value
      - "echo_instruction": paste back the instruction as the answer
    """

    def __init__(self, name: str = "dummy", policy: str = "first_slot", seed: int = 0):
        self.name = name
        self.policy = policy
        self.rng = random.Random(seed)
        self.last_tokens = 100

    def observe(self, observation: dict) -> None:
        return None

    def propose_action(self, state: dict, ledger: dict) -> ActionProposal:
        task = ledger.get("task", {})
        surfaces = ledger.get("surfaces") or []
        surface_id = surfaces[0]["id"] if surfaces else "final_answer"
        variables = ledger.get("variables") or []
        instruction = task.get("instruction", "")

        candidates: list[Any] = [v.get("value") for v in variables if v.get("value") is not None]

        payload_value: Any
        if self.policy == "first_slot" and candidates:
            payload_value = candidates[0]
        elif self.policy == "last_slot" and candidates:
            payload_value = candidates[-1]
        elif self.policy == "random_slot" and candidates:
            payload_value = self.rng.choice(candidates)
        elif self.policy == "constant":
            payload_value = "constant"
        else:
            payload_value = instruction[:40]

        return ActionProposal(
            action_id=f"dummy_{state.get('step', 0)}",
            surface_id=surface_id,
            action_type="answer",
            payload={"value": payload_value},
            rationale=f"policy={self.policy}",
            claimed_variables_used=[v["id"] for v in variables[:1]],
        )


class OracleAgent:
    """Agent that uses task metadata to always emit the correct action.

    Used to verify environments, gates, and scoring end-to-end.
    """

    name = "oracle"
    last_tokens = 50

    def observe(self, observation: dict) -> None:
        return None

    def propose_action(self, state: dict, ledger: dict) -> ActionProposal:
        task = ledger.get("task", {})
        meta = task.get("metadata", {}) or {}
        surfaces = ledger.get("surfaces") or []
        surface_id = surfaces[0]["id"] if surfaces else "final_answer"

        # Environments record the expected payload under metadata.expected_payload.
        payload = meta.get("expected_payload", {"value": meta.get("expected_answer")})
        return ActionProposal(
            action_id=f"oracle_{state.get('step', 0)}",
            surface_id=surface_id,
            action_type=meta.get("expected_action_type", "answer"),
            payload=payload,
            rationale="oracle uses task metadata",
            claimed_variables_used=meta.get("critical_variable_ids", []),
        )
