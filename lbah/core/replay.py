"""Proof-of-Execution-style replay capture for LLM (and tool) I/O.

The concern harness makes replayability a first-class claim: given a completed
run's event log, a fresh run using this module's :class:`ReplayModelAdapter`
must produce bit-identical commitments. The design roadmap (§5 Risks and
Phase 1 task 1) is explicit that a probe is only as trustworthy as replay
determinism, and that we should adopt PoE-style capture of tool/LLM I/O
before claiming reproducibility.

This module supplies the base envelope + a model-side capture wrapper. The
coding stack (see :mod:`lbah.coding.replay`) layers a tool-side executor on
top for full replay of a coding run's commitments.

Design notes:

* Envelopes are ordered by ``call_index`` — a monotonic integer assigned as
  ``.complete()`` is invoked. Replay consumes them in that order.
* On replay, the request the fresh model receives must match the captured
  request under a normalisation that ignores non-load-bearing formatting
  (dict key order, ``None`` fields). Mismatch raises
  :class:`ReplayMismatchError` with a diff — the whole point of PoE capture
  is that surprise divergence is loud, not silent.
* Capture is opt-in on runners so the existing hot path pays nothing.
"""

from __future__ import annotations

import copy
import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .events import ConcernEventLog


class IOEnvelope(BaseModel):
    """One PoE-style capture of a model ``.complete()`` request/response."""

    model_config = ConfigDict(extra="allow")

    call_index: int
    request: dict[str, Any] = Field(default_factory=dict)
    response: dict[str, Any] = Field(default_factory=dict)
    adapter_name: str | None = None


class ReplayMismatchError(AssertionError):
    """Raised when a replayed ``.complete()`` call diverges from the envelope."""

    def __init__(self, call_index: int, expected: dict, actual: dict, diff: str):
        self.call_index = call_index
        self.expected = expected
        self.actual = actual
        self.diff = diff
        super().__init__(
            f"replay request mismatch at call_index={call_index}:\n{diff}"
        )


def _normalise_request(
    messages: list[dict] | None,
    *,
    schema: dict | None,
    tools: list[dict] | None,
    temperature: float | None,
    max_tokens: int | None,
) -> dict[str, Any]:
    """Canonical form of a ``.complete()`` request for replay matching.

    Wall-clock jitter is not a factor here (there is none); this exists so
    keyword-arg identity does not depend on Python dict iteration order.
    """
    payload = {
        "messages": list(messages or []),
        "schema": schema,
        "tools": list(tools or []) if tools else None,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    return json.loads(json.dumps(payload, sort_keys=True, default=str))


def _diff_requests(expected: dict, actual: dict) -> str:
    import difflib

    exp = json.dumps(expected, indent=2, sort_keys=True, default=str).splitlines()
    act = json.dumps(actual, indent=2, sort_keys=True, default=str).splitlines()
    return "\n".join(
        difflib.unified_diff(exp, act, fromfile="expected", tofile="actual", lineterm="")
    )


class CapturingModelAdapter:
    """Wraps a ``ModelAdapter`` and records each call as a ``record_llm_io`` event.

    The wrapper delegates to the underlying adapter unchanged; capture is
    additive. Every call is stamped with a monotonic ``call_index`` scoped to
    this wrapper instance so replay ordering is unambiguous even when a
    single log has envelopes from several adapters.
    """

    def __init__(self, inner: Any, event_log: Any, *, source: str = "capture_llm_io"):
        self.inner = inner
        self.event_log = event_log
        self.source = source
        self.name = getattr(inner, "name", "captured")
        self._counter = 0

    @property
    def last_tokens(self) -> int:
        return int(getattr(self.inner, "last_tokens", 0) or 0)

    def complete(
        self,
        messages: list[dict],
        *,
        schema: dict | None = None,
        tools: list[dict] | None = None,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> dict:
        response = self.inner.complete(
            messages,
            schema=schema,
            tools=tools,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        request = _normalise_request(
            messages,
            schema=schema,
            tools=tools,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        call_index = self._counter
        self._counter += 1
        envelope = IOEnvelope(
            call_index=call_index,
            request=request,
            response=copy.deepcopy(response),
            adapter_name=self.name,
        )
        self.event_log.append(
            "record_llm_io",
            payload=envelope.model_dump(),
            source=self.source,
        )
        return response

    def observe(self, observation: dict) -> None:
        if hasattr(self.inner, "observe"):
            self.inner.observe(observation)


def capture_llm_io(model_adapter: Any, event_log: Any, *, source: str = "capture_llm_io"):
    """Wrap ``model_adapter`` so every ``.complete()`` records an envelope."""
    return CapturingModelAdapter(model_adapter, event_log, source=source)


class ReplayModelAdapter:
    """Model adapter that replays captured envelopes in ``call_index`` order.

    * Responses are returned in ascending ``call_index`` order.
    * Each incoming request must match the captured envelope's request (under
      :func:`_normalise_request`). A mismatch raises :class:`ReplayMismatchError`.
    * Running out of envelopes raises :class:`ReplayMismatchError` too — the
      caller ran the model more times than was captured.
    """

    def __init__(self, envelopes: list[IOEnvelope], *, name: str = "replay"):
        self.name = name
        self._envelopes = sorted(envelopes, key=lambda e: e.call_index)
        self._cursor = 0
        self.last_tokens = 0

    def complete(
        self,
        messages: list[dict],
        *,
        schema: dict | None = None,
        tools: list[dict] | None = None,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> dict:
        actual = _normalise_request(
            messages,
            schema=schema,
            tools=tools,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        if self._cursor >= len(self._envelopes):
            raise ReplayMismatchError(
                call_index=self._cursor,
                expected={},
                actual=actual,
                diff="no more envelopes to replay",
            )
        envelope = self._envelopes[self._cursor]
        if envelope.request != actual:
            raise ReplayMismatchError(
                call_index=envelope.call_index,
                expected=envelope.request,
                actual=actual,
                diff=_diff_requests(envelope.request, actual),
            )
        self._cursor += 1
        return copy.deepcopy(envelope.response)

    def observe(self, observation: dict) -> None:
        return None


def envelopes_from_log(event_log: ConcernEventLog | Any) -> list[IOEnvelope]:
    """Extract ``record_llm_io`` envelopes from a log, in ``call_index`` order.

    Works for both :class:`~lbah.core.events.ConcernEventLog` and the coding
    log — both share the ``events`` collection shape used here.
    """
    envelopes: list[IOEnvelope] = []
    for event in event_log.events:
        if event.type != "record_llm_io":
            continue
        envelopes.append(IOEnvelope.model_validate(event.payload))
    return sorted(envelopes, key=lambda e: e.call_index)
