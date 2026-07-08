"""Environment for stale-confidence / reopenability tasks."""

from __future__ import annotations

import copy
from typing import Any

from ..core.schemas import (
    ActionProposal,
    ConcernLedger,
    Observation,
    State,
    TaskSpec,
)
from .base import Environment


class MemoryEnv(Environment):
    """A world whose true state has shifted since the agent stored a rule.

    Task metadata:
        - stored_beliefs: dict[key, old_value]
        - current_state: dict[key, current_value]
        - critical_keys: list[str]
    """

    terminal_on_block = False

    def __init__(self):
        self.stale_values: dict[str, Any] = {}
        self.recheck_count = 0

    def reset(self, task: TaskSpec) -> State:
        meta = task.metadata or {}
        self.stale_values = copy.deepcopy(meta.get("stored_beliefs", {}) or {})
        self.recheck_count = 0
        return State(
            task_id=task.task_id,
            step=0,
            done=False,
            scratch={
                "stored_beliefs": copy.deepcopy(meta.get("stored_beliefs", {}) or {}),
                "current_state": copy.deepcopy(meta.get("current_state", {}) or {}),
                "rechecks": [],
                "_task_metadata": meta,
            },
        )

    def execute(self, proposal: ActionProposal, state: State) -> State:
        state.step += 1
        cur = state.scratch.get("current_state", {})
        if proposal.action_type == "recheck":
            key = proposal.payload.get("key")
            state.scratch["rechecks"].append(key)
            self.recheck_count += 1
            state.last_observation = Observation(
                text=f"rechecked '{key}' -> {cur.get(key)}",
                data={"key": key, "current_value": cur.get(key)},
            )
        else:
            key = proposal.payload.get("key")
            value = proposal.payload.get("value")
            cur[key] = value
            state.last_observation = Observation(
                text=f"wrote '{key}' = {value}",
            )
            state.done = True
        return state

    def done(self, state: State) -> bool:
        return state.done or state.step >= 5

    def success(self, state: State) -> bool:
        current = state.scratch.get("current_state", {})
        expected = (state.scratch.get("_task_metadata") or {}).get("expected_write", {})
        if not expected:
            return state.done
        for k, v in expected.items():
            if current.get(k) != v:
                return False
        return True
