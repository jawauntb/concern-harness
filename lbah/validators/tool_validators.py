"""Validators for tool-call commitment surfaces."""

from __future__ import annotations

from typing import Any

from ..core.schemas import ActionProposal, ConcernLedger, GateResult, State


def _tool_schema(ledger: ConcernLedger, proposal: ActionProposal) -> dict:
    schemas = (ledger.task.metadata or {}).get("tool_schemas", {}) or {}
    tool_name = proposal.payload.get("tool") or proposal.action_type
    return schemas.get(tool_name, {}) or {}


def schema_valid(
    proposal: ActionProposal, ledger: ConcernLedger, state: State, env: Any
) -> GateResult:
    schema = _tool_schema(ledger, proposal)
    if not schema:
        return GateResult(
            gate_name="validator::schema_valid",
            passed=True,
            score=1.0,
            reason="no schema registered for tool; skipped",
            weight=0.2,
        )
    args = proposal.payload.get("args", proposal.payload)
    props = schema.get("properties", {})
    types = {"string": str, "integer": int, "number": (int, float), "boolean": bool, "array": list, "object": dict}
    errors: list[str] = []
    for key, spec in props.items():
        if key not in args:
            continue
        expected = types.get(spec.get("type"))
        if expected and not isinstance(args[key], expected):
            errors.append(f"{key} expected {spec.get('type')}, got {type(args[key]).__name__}")
    passed = not errors
    return GateResult(
        gate_name="validator::schema_valid",
        passed=passed,
        score=1.0 if passed else 0.0,
        reason="schema valid" if passed else "; ".join(errors),
        evidence={"errors": errors},
    )


def required_fields_present(
    proposal: ActionProposal, ledger: ConcernLedger, state: State, env: Any
) -> GateResult:
    schema = _tool_schema(ledger, proposal)
    required = schema.get("required") or (ledger.task.metadata or {}).get("required_fields", [])
    args = proposal.payload.get("args", proposal.payload)
    missing = [f for f in required if f not in args or args[f] in (None, "", [], {})]
    passed = not missing
    return GateResult(
        gate_name="validator::required_fields_present",
        passed=passed,
        score=1.0 if passed else 0.0,
        reason="all required fields present" if passed else f"missing fields: {missing}",
        evidence={"missing": missing, "required": list(required)},
    )


def forbidden_fields_absent(
    proposal: ActionProposal, ledger: ConcernLedger, state: State, env: Any
) -> GateResult:
    forbidden = (ledger.task.metadata or {}).get("forbidden_fields", []) or []
    forbidden_values = (ledger.task.metadata or {}).get("forbidden_values", {}) or {}
    args = proposal.payload.get("args", proposal.payload)
    present = [f for f in forbidden if f in args]
    value_hits: list[str] = []
    for field, forbidden_vs in forbidden_values.items():
        val = args.get(field)
        if val is None:
            continue
        vs_list = forbidden_vs if isinstance(forbidden_vs, list) else [forbidden_vs]
        if isinstance(val, list):
            for entry in val:
                if entry in vs_list:
                    value_hits.append(f"{field}={entry}")
        elif val in vs_list:
            value_hits.append(f"{field}={val}")
    passed = not present and not value_hits
    return GateResult(
        gate_name="validator::forbidden_fields_absent",
        passed=passed,
        score=1.0 if passed else 0.0,
        reason=(
            "no forbidden fields or values"
            if passed
            else f"forbidden fields present={present} value_hits={value_hits}"
        ),
        evidence={"present": present, "value_hits": value_hits},
    )


def irreversible_confirmed(
    proposal: ActionProposal, ledger: ConcernLedger, state: State, env: Any
) -> GateResult:
    surface = ledger.surface_by_id(proposal.surface_id)
    if surface is None or not surface.irreversible:
        return GateResult(
            gate_name="validator::irreversible_confirmed",
            passed=True,
            score=1.0,
            reason="surface not irreversible",
            weight=0.1,
        )
    confirmed = bool(proposal.payload.get("confirmed", False))
    return GateResult(
        gate_name="validator::irreversible_confirmed",
        passed=confirmed,
        score=1.0 if confirmed else 0.0,
        reason="confirmed" if confirmed else "irreversible action lacks explicit confirmation",
        weight=1.0,
    )
