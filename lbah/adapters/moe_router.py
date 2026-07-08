"""Concern-weighted MoE router.

Wraps a bank of experts (any AgentAdapter/ModelAdapter). For each proposal
opportunity it picks the expert whose competence best matches the top
commitment surface and highest-concern variable in the ledger.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..core.schemas import ActionProposal


@dataclass
class Expert:
    key: str
    agent: Any
    competences: dict[str, float]  # surface_type or variable_tag -> competence in [0,1]
    cost: float = 1.0


class ConcernMoERouter:
    """Route each step to the expert with the best expected commitment effect."""

    def __init__(
        self,
        name: str,
        experts: list[Expert],
        default_expert: str | None = None,
    ):
        self.name = name
        self.experts: dict[str, Expert] = {e.key: e for e in experts}
        if not self.experts:
            raise ValueError("MoE router needs at least one expert")
        self.default_expert = default_expert or next(iter(self.experts.keys()))
        self.last_tokens = 0
        self._last_expert: str | None = None
        self._history: list[str] = []

    # ------------------------------------------------------------------

    def _route_score(self, expert: Expert, surface_type: str, tags: list[str]) -> float:
        surface_score = expert.competences.get(surface_type, 0.0)
        tag_score = max([expert.competences.get(t, 0.0) for t in tags] or [0.0])
        return (0.6 * surface_score + 0.4 * tag_score) / max(expert.cost, 1e-6)

    def route(self, ledger: dict) -> Expert:
        surfaces = ledger.get("surfaces") or []
        surface_type = surfaces[0].get("type", "final_answer") if surfaces else "final_answer"
        variables = ledger.get("variables") or []
        variables.sort(key=lambda v: v.get("concern", 0), reverse=True)
        tags: list[str] = []
        for v in variables[:3]:
            tags.extend(v.get("proxy_risks", []) or [])
            tags.append(v.get("name", ""))

        best_key = self.default_expert
        best_score = -1.0
        for key, expert in self.experts.items():
            score = self._route_score(expert, surface_type, tags)
            if score > best_score:
                best_score = score
                best_key = key
        return self.experts[best_key]

    # ------------------------------------------------------------------

    def observe(self, observation: dict) -> None:
        for e in self.experts.values():
            observer = getattr(e.agent, "observe", None)
            if callable(observer):
                observer(observation)

    def propose_action(self, state: dict, ledger: dict) -> ActionProposal:
        expert = self.route(ledger)
        self._last_expert = expert.key
        self._history.append(expert.key)
        proposal = expert.agent.propose_action(state, ledger)
        self.last_tokens = getattr(expert.agent, "last_tokens", 0)
        if proposal.rationale:
            proposal.rationale = f"[expert={expert.key}] {proposal.rationale}"
        else:
            proposal.rationale = f"expert={expert.key}"
        return proposal
