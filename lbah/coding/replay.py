"""Coding-side PoE replay: reconstruct a completed run from its event log.

Paired with :mod:`lbah.core.replay`. The core module captures LLM I/O; the
coding runner also captures tool I/O (the paired action + observation for
every executed action). Together, they let a replay reproduce the exact
commitments a previous run made — no workspace, no filesystem, no test
subprocesses required.

The intended use is verification of certificate/replay claims: a probe that
says "this run's commitment is a function of the ledger" can be checked by
replaying it and asserting the same commitment.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from ..core.replay import ReplayMismatchError, ReplayModelAdapter, envelopes_from_log
from .actions import CodingAction, CodingObservation
from .events import CodingEventLog


class ToolEnvelope(BaseModel):
    """Paired capture of one executed action + the observation it produced."""

    step: int
    action: dict[str, Any] = Field(default_factory=dict)
    observation: dict[str, Any] = Field(default_factory=dict)


def tool_envelopes_from_log(event_log: CodingEventLog) -> list[ToolEnvelope]:
    """Extract ``record_tool_io`` envelopes from a coding event log, in order."""
    envelopes: list[ToolEnvelope] = []
    step = 0
    for event in sorted(event_log.events, key=lambda e: e.seq):
        if event.type != "record_tool_io":
            continue
        payload = dict(event.payload or {})
        envelopes.append(
            ToolEnvelope(
                step=step,
                action=dict(payload.get("action") or {}),
                observation=dict(payload.get("observation") or {}),
            )
        )
        step += 1
    return envelopes


class ReplayToolExecutor:
    """Serves observations from a captured coding log in the order they occurred.

    The replay contract is strict: the caller must issue actions in the same
    order as the captured run, with the same ``action_type``. Any deviation
    raises :class:`~lbah.core.replay.ReplayMismatchError` — replay is a
    verification move, not a "best effort" match.
    """

    def __init__(self, envelopes: list[ToolEnvelope]):
        self._envelopes = list(envelopes)
        self._cursor = 0

    @property
    def exhausted(self) -> bool:
        return self._cursor >= len(self._envelopes)

    def execute(self, action: CodingAction) -> CodingObservation:
        if self.exhausted:
            raise ReplayMismatchError(
                call_index=self._cursor,
                expected={},
                actual=action.model_dump(),
                diff="no more tool envelopes to replay",
            )
        envelope = self._envelopes[self._cursor]
        expected_type = envelope.action.get("action_type")
        if expected_type != action.action_type:
            raise ReplayMismatchError(
                call_index=self._cursor,
                expected=envelope.action,
                actual=action.model_dump(),
                diff=(
                    f"expected action_type={expected_type!r}, "
                    f"got {action.action_type!r} at step {self._cursor}"
                ),
            )
        self._cursor += 1
        return CodingObservation.model_validate(envelope.observation)


class ReplayCodingBundle(BaseModel):
    """A model + tool executor pair ready to replay a captured coding run."""

    model_config = {"arbitrary_types_allowed": True}

    model: Any
    tool_executor: Any
    llm_envelopes: int
    tool_envelopes: int


def bundle_from_log(event_log: CodingEventLog) -> ReplayCodingBundle:
    """Build a :class:`ReplayModelAdapter` + :class:`ReplayToolExecutor` from a log.

    The returned bundle is enough for a byte-identical replay of the previous
    run's commitments: swap the agent's model for ``bundle.model`` and route
    action execution through ``bundle.tool_executor``. The commitments
    (final diff, ledger, certificate inputs) are a deterministic function of
    those two streams.
    """
    llm = envelopes_from_log(event_log)
    tools = tool_envelopes_from_log(event_log)
    return ReplayCodingBundle(
        model=ReplayModelAdapter(llm),
        tool_executor=ReplayToolExecutor(tools),
        llm_envelopes=len(llm),
        tool_envelopes=len(tools),
    )
