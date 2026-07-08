"""Environment for browser-action tasks (simulated only)."""

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


class BrowserEnv(Environment):
    """Simulated browser.

    Task metadata:
        - expected_url: str
        - forbidden_url_fragments: list[str]
        - required_selectors: list[str]
    """

    terminal_on_block = False

    def reset(self, task: TaskSpec) -> State:
        return State(
            task_id=task.task_id,
            step=0,
            done=False,
            scratch={"pages_visited": [], "clicks": []},
        )

    def execute(self, proposal: ActionProposal, state: State) -> State:
        state.step += 1
        if proposal.action_type == "navigate":
            url = proposal.payload.get("url", "")
            state.scratch["pages_visited"].append(url)
            state.last_observation = Observation(text=f"navigated to {url}")
        elif proposal.action_type == "click":
            selector = proposal.payload.get("selector", "")
            state.scratch["clicks"].append(selector)
            state.last_observation = Observation(text=f"clicked {selector}")
        elif proposal.action_type in {"submit", "final_answer"}:
            state.last_observation = Observation(text="task complete", data=proposal.payload)
            state.done = True
        else:
            state.last_observation = Observation(text=f"unknown action {proposal.action_type}")
        return state

    def done(self, state: State) -> bool:
        return state.done or state.step >= 8

    def success(self, state: State) -> bool:
        return state.done

    def proxy_checks(
        self,
        proposal: ActionProposal,
        ledger: ConcernLedger,
        state: State,
    ) -> list[GateResult]:
        forbidden = (ledger.task.metadata or {}).get("forbidden_url_fragments", []) or []
        url = proposal.payload.get("url", "")
        hits = [f for f in forbidden if f in str(url)]
        return [
            GateResult(
                gate_name="proxy::forbidden_url_fragment",
                passed=not hits,
                score=0.0 if hits else 1.0,
                reason=f"forbidden url fragments: {hits}" if hits else "no forbidden fragments",
                weight=1.0,
            )
        ]
