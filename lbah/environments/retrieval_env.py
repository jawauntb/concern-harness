"""Environment for retrieval / citation faithfulness tasks."""

from __future__ import annotations

from typing import Any

from ..core.schemas import (
    ActionProposal,
    ConcernLedger,
    GateResult,
    Observation,
    State,
    TaskSpec,
)
from .base import Environment


class RetrievalEnv(Environment):
    """A read-only doc index plus a final-answer surface.

    Task metadata:
        - documents: dict[doc_id, text]
        - required_claims: list[str] — semantic tokens the final answer must cover
        - contradicting_docs: list[doc_id]
    """

    def reset(self, task: TaskSpec) -> State:
        return State(
            task_id=task.task_id,
            step=0,
            done=False,
            scratch={"queries": [], "_task_metadata": task.metadata or {}},
        )

    def execute(self, proposal: ActionProposal, state: State) -> State:
        state.step += 1
        if proposal.action_type == "query":
            q = proposal.payload.get("query", "").lower()
            docs = (state.scratch.get("_task_metadata") or {}).get("documents", {}) or {}
            hits = [k for k, v in docs.items() if q and q in str(v).lower()]
            state.scratch["queries"].append({"q": q, "hits": hits})
            state.last_observation = Observation(
                text=f"query returned {len(hits)} docs",
                data={"hits": hits},
            )
        else:
            state.last_observation = Observation(
                text="final answer submitted",
                data={"answer": proposal.payload.get("answer")},
            )
            state.done = True
        return state

    def done(self, state: State) -> bool:
        return state.done or state.step >= 6

    def success(self, state: State) -> bool:
        if not state.done:
            return False
        return True

    def proxy_checks(
        self,
        proposal: ActionProposal,
        ledger: ConcernLedger,
        state: State,
    ) -> list[GateResult]:
        if proposal.action_type != "answer":
            return []
        docs = (ledger.task.metadata or {}).get("documents", {}) or {}
        contradicting = (ledger.task.metadata or {}).get("contradicting_docs", []) or []
        cited = [c.get("citation") if isinstance(c, dict) else None
                 for c in proposal.payload.get("claims", []) or []]
        cited = [c for c in cited if c]
        contradict_cited = [c for c in cited if c in contradicting]
        return [
            GateResult(
                gate_name="proxy::cites_contradicting_source",
                passed=not contradict_cited,
                score=0.0 if contradict_cited else 1.0,
                reason=(
                    f"cited contradicting sources: {contradict_cited}"
                    if contradict_cited
                    else "no contradicting citations"
                ),
                weight=0.9,
            ),
        ]
