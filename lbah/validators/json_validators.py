"""Simple JSON-shape validators."""

from __future__ import annotations

from typing import Any

from ..core.schemas import ActionProposal, ConcernLedger, GateResult, State


def field_present(
    proposal: ActionProposal, ledger: ConcernLedger, state: State, env: Any
) -> GateResult:
    field = (ledger.task.metadata or {}).get("field_to_check")
    if not field:
        return GateResult(
            gate_name="validator::field_present",
            passed=True,
            score=1.0,
            reason="no field_to_check declared; skipped",
            weight=0.1,
        )
    ok = field in proposal.payload
    return GateResult(
        gate_name="validator::field_present",
        passed=ok,
        score=1.0 if ok else 0.0,
        reason=f"field '{field}' {'present' if ok else 'missing'}",
    )


def field_type_valid(
    proposal: ActionProposal, ledger: ConcernLedger, state: State, env: Any
) -> GateResult:
    field = (ledger.task.metadata or {}).get("field_to_check")
    expected_type = (ledger.task.metadata or {}).get("field_type", "string")
    types = {"string": str, "integer": int, "number": (int, float), "boolean": bool, "array": list, "object": dict}
    if not field or field not in proposal.payload:
        return GateResult(
            gate_name="validator::field_type_valid",
            passed=True,
            score=1.0,
            reason="no field to validate",
            weight=0.1,
        )
    expected = types.get(expected_type, str)
    ok = isinstance(proposal.payload[field], expected)
    return GateResult(
        gate_name="validator::field_type_valid",
        passed=ok,
        score=1.0 if ok else 0.0,
        reason=(
            f"field '{field}' has type {expected_type}"
            if ok
            else f"field '{field}' expected {expected_type}, got {type(proposal.payload[field]).__name__}"
        ),
    )
