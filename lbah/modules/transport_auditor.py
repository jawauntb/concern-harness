"""Transport auditor: did the high-concern variables reach the action?"""

from __future__ import annotations

import json
from typing import Any

from ..core.schemas import ActionProposal, ConcernLedger, GateResult, State


def _flatten(value: Any) -> list[Any]:
    """Flatten nested structures into a list of primitive leaves."""
    out: list[Any] = []

    def walk(v: Any) -> None:
        if isinstance(v, dict):
            for x in v.values():
                walk(x)
        elif isinstance(v, (list, tuple)):
            for x in v:
                walk(x)
        else:
            out.append(v)

    walk(value)
    return out


def _string_of(payload: Any) -> str:
    try:
        return json.dumps(payload, default=str)
    except Exception:
        return str(payload)


class TransportAuditor:
    """Deterministic transport check: variable value must appear in proposal payload.

    An LLM-backed subclass could replace this with a semantic check.
    """

    def __init__(self, min_concern: float = 0.0):
        self.min_concern = min_concern

    def check(
        self,
        proposal: ActionProposal,
        ledger: ConcernLedger,
        state: State,
    ) -> list[GateResult]:
        results: list[GateResult] = []
        payload_str = _string_of(proposal.payload).lower()
        payload_leaves = [str(x).lower() for x in _flatten(proposal.payload) if x is not None]

        for var in ledger.variables:
            if var.concern < self.min_concern:
                continue
            # Only audit variables whose required_surfaces list includes this surface.
            if var.required_surfaces and proposal.surface_id not in var.required_surfaces:
                continue
            # Forbidden-tagged variables must NOT appear in the payload — the
            # proxy adversary handles that. Skip them here.
            if "forbidden" in [r.lower() for r in var.proxy_risks]:
                continue

            expected = var.value
            if expected is None:
                # Nothing concrete to search for — skip transport, but note.
                results.append(
                    GateResult(
                        gate_name=f"transport::{var.id}",
                        gate_kind="transport",
                        passed=True,
                        score=1.0,
                        reason="variable has no concrete value; transport unchecked",
                        concern_id=var.id,
                        weight=var.concern,
                    )
                )
                continue

            expected_str = str(expected).lower()

            leaf_hit = expected_str in payload_leaves
            substr_hit = expected_str in payload_str
            passed = leaf_hit or substr_hit

            results.append(
                GateResult(
                    gate_name=f"transport::{var.id}",
                    gate_kind="transport",
                    passed=passed,
                    score=1.0 if passed else 0.0,
                    reason=(
                        f"variable '{var.id}' present in payload"
                        if passed
                        else f"variable '{var.id}' expected value '{expected}' missing from payload"
                    ),
                    evidence={
                        "expected": expected,
                        "leaf_hit": leaf_hit,
                        "substr_hit": substr_hit,
                        "payload": proposal.payload,
                    },
                    concern_id=var.id,
                    weight=var.concern,
                )
            )
        return results
