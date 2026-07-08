"""Small coding agents for deterministic tests and scripted demos."""

from __future__ import annotations

from .actions import CodingAction


class ScriptedCodingAgent:
    """Returns a fixed sequence of coding actions.

    This is not meant to be competitive. It gives tests, docs, and benchmark
    harness smoke runs a deterministic agent while model-backed coding agents
    can implement the same ``propose_action``/``observe`` pair.
    """

    def __init__(self, actions: list[CodingAction], name: str = "scripted_coder"):
        self.name = name
        self.actions = list(actions)
        self.observations: list[dict] = []
        self.last_tokens = 0
        self._index = 0

    def propose_action(self, state: dict, ledger: dict) -> CodingAction:
        if self._index >= len(self.actions):
            return CodingAction(
                action_id=f"{self.name}_finish_{self._index}",
                action_type="finish",
                rationale="script exhausted",
            )
        action = self.actions[self._index]
        self._index += 1
        return action

    def observe(self, observation: dict) -> None:
        self.observations.append(observation)
