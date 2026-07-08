"""Environment for tool-call tasks (moved-bottleneck, tool constraints)."""

from __future__ import annotations

from typing import Any

from ..core.schemas import (
    ActionProposal,
    LoadBearingCertificate,
    Observation,
    State,
    TaskSpec,
)
from .base import Environment


class ToolUseEnv(Environment):
    """Executes tool calls against an in-memory registry of tool handlers.

    Task metadata:
        - expected_payload: dict — the canonical payload for oracle checking
        - expected_action_type: str — what tool the action should target
        - critical_variable_ids: list[str] — variables that must reach the action
    """

    terminal_on_block = False

    def __init__(self):
        self.tool_calls: list[dict] = []

    # ------------------------------------------------------------------

    def reset(self, task: TaskSpec) -> State:
        self.tool_calls = []
        return State(
            task_id=task.task_id,
            step=0,
            done=False,
            scratch={"tool_calls": [], "_task_metadata": task.metadata or {}},
        )

    def execute(self, proposal: ActionProposal, state: State) -> State:
        state.step += 1
        record = {
            "surface_id": proposal.surface_id,
            "action_type": proposal.action_type,
            "payload": proposal.payload,
        }
        self.tool_calls.append(record)
        state.scratch.setdefault("tool_calls", []).append(record)
        state.last_observation = Observation(
            text=f"tool {proposal.action_type} executed",
            data={"result": "ok", "record": record},
        )
        state.done = True
        return state

    def observe_block(
        self,
        proposal: ActionProposal,
        cert: LoadBearingCertificate,
        state: State,
    ) -> State:
        state.step += 1
        state.last_observation = Observation(
            text=f"BLOCKED: {cert.summary}",
            data={"cert": cert.model_dump(), "attempted_payload": proposal.payload},
        )
        # Blocking is terminal for the current step but not for the whole task.
        return state

    def done(self, state: State) -> bool:
        return state.done or state.step >= 5

    def success(self, state: State) -> bool:
        # We succeed if the last executed tool call's payload matches expected_payload.
        expected = (state.scratch.get("_task_metadata") or {}).get("expected_payload")
        if expected is None:
            return state.done
        if not self.tool_calls:
            return False
        last = self.tool_calls[-1]["payload"]
        # Compare on the fields present in expected only.
        for k, v in expected.items():
            if last.get(k) != v:
                return False
        return True
