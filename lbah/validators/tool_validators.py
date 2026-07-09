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


# ---------------------------------------------------------------------------
# ToolFailBench / ToolScan categories (coding-trace aware)
# ---------------------------------------------------------------------------


def _coding_trace(state: State) -> list[dict[str, Any]]:
    raw = (state.scratch or {}).get("coding_trace") or []
    return raw if isinstance(raw, list) else []


def _toolish_actions(trace: list[dict[str, Any]]) -> list[dict[str, Any]]:
    toolish = {"read_file", "search", "run_command", "run_tests", "inspect"}
    out: list[dict[str, Any]] = []
    for entry in trace:
        action = entry.get("action") or {}
        if action.get("action_type") in toolish:
            out.append(entry)
    return out


def result_ignore(
    proposal: ActionProposal, ledger: ConcernLedger, state: State, env: Any
) -> GateResult:
    """Transport: tool returned data but the commitment does not reflect it.

    Heuristic for coding: a successful read/search/test observation whose
    distinctive content never appears in the finish diff / claimed payload.
    """
    trace = _coding_trace(state)
    final_diff = str((state.scratch or {}).get("final_diff") or proposal.payload.get("diff") or "")
    ignored: list[str] = []
    for entry in _toolish_actions(trace):
        obs = entry.get("observation") or {}
        if not obs.get("success"):
            continue
        data = obs.get("data") or {}
        # Distinctive snippets from tool results that should influence the patch.
        candidates: list[str] = []
        if isinstance(data.get("content"), str) and len(data["content"]) >= 8:
            # Use a short stable fingerprint from the middle of the read.
            content = data["content"]
            mid = content[len(content) // 3 : len(content) // 3 + 24].strip()
            if mid:
                candidates.append(mid)
        for match in data.get("matches") or []:
            if isinstance(match, dict) and match.get("line"):
                candidates.append(str(match["line"])[:40])
        for snippet in candidates:
            if snippet and snippet not in final_diff and snippet not in str(proposal.payload):
                # Only flag when the agent later finished without using the read.
                if any(
                    (e.get("action") or {}).get("action_type") == "finish"
                    for e in trace
                ):
                    ignored.append(snippet[:80])
    # Soft gate: absence of ignored snippets is pass; presence is a transport warning.
    # Avoid false positives when no tool reads happened.
    if not _toolish_actions(trace):
        return GateResult(
            gate_name="transport::result_ignore",
            gate_kind="transport",
            passed=True,
            score=1.0,
            reason="no tool observations to transport",
            weight=0.3,
        )
    # Only fail when we have a clear unused fingerprint AND no edits followed the read.
    edits_after_reads = any(
        (e.get("action") or {}).get("action_type") == "edit_file" for e in trace
    )
    passed = not ignored or edits_after_reads
    return GateResult(
        gate_name="transport::result_ignore",
        gate_kind="transport",
        passed=passed,
        score=1.0 if passed else 0.4,
        reason=(
            "tool results appear used or followed by edits"
            if passed
            else f"tool result fingerprints absent from commitment: {ignored[:3]}"
        ),
        evidence={"ignored_snippets": ignored[:5], "edits_after_reads": edits_after_reads},
        weight=0.6,
    )


def output_fabrication(
    proposal: ActionProposal, ledger: ConcernLedger, state: State, env: Any
) -> GateResult:
    """Proxy: commitment cites tool output that was never observed."""
    trace = _coding_trace(state)
    claimed = proposal.payload.get("claimed_tool_outputs") or proposal.payload.get("citations") or []
    if not isinstance(claimed, list) or not claimed:
        return GateResult(
            gate_name="proxy::output_fabrication",
            gate_kind="proxy",
            passed=True,
            score=1.0,
            reason="no explicit tool-output claims to audit",
            weight=0.3,
        )
    observed_text = []
    for entry in trace:
        obs = entry.get("observation") or {}
        observed_text.append(str(obs.get("message") or ""))
        observed_text.append(str(obs.get("data") or ""))
    blob = "\n".join(observed_text)
    fabricated = [c for c in claimed if str(c) and str(c) not in blob]
    passed = not fabricated
    return GateResult(
        gate_name="proxy::output_fabrication",
        gate_kind="proxy",
        passed=passed,
        score=1.0 if passed else 0.0,
        reason="claimed tool outputs observed" if passed else f"fabricated claims: {fabricated[:3]}",
        evidence={"fabricated": fabricated[:5]},
        weight=0.8,
    )


def tool_skip(
    proposal: ActionProposal, ledger: ConcernLedger, state: State, env: Any
) -> GateResult:
    """Concern under-acquisition: high-concern items lack evidence and no tools ran."""
    trace = _coding_trace(state)
    coding_ledger = (state.scratch or {}).get("coding_ledger") or {}
    concerns = coding_ledger.get("concerns") or []
    high_open = [
        c
        for c in concerns
        if float(c.get("concern", 0)) >= 0.7
        and c.get("status") == "open"
        and not c.get("evidence")
    ]
    tools = _toolish_actions(trace)
    if not high_open:
        return GateResult(
            gate_name="validator::tool_skip",
            gate_kind="validator",
            passed=True,
            score=1.0,
            reason="no high-concern open items without evidence",
            weight=0.4,
        )
    passed = bool(tools)
    return GateResult(
        gate_name="validator::tool_skip",
        gate_kind="validator",
        passed=passed,
        score=1.0 if passed else 0.0,
        reason=(
            "tools were used for open high-concern items"
            if passed
            else f"skipped tools while {len(high_open)} high-concern item(s) lack evidence"
        ),
        evidence={"open_high_concern_ids": [c.get("id") for c in high_open][:8]},
        weight=0.7,
    )


def unnecessary_tool_use(
    proposal: ActionProposal, ledger: ConcernLedger, state: State, env: Any
) -> GateResult:
    """Concern over-acquisition: many tool calls with no concern linkage."""
    trace = _coding_trace(state)
    tools = _toolish_actions(trace)
    if len(tools) < 4:
        return GateResult(
            gate_name="validator::unnecessary_tool_use",
            gate_kind="validator",
            passed=True,
            score=1.0,
            reason="tool-use volume within budget",
            weight=0.2,
        )
    linked = 0
    for entry in tools:
        action = entry.get("action") or {}
        if action.get("concerns_addressed") or action.get("rationale"):
            linked += 1
    ratio = linked / len(tools)
    passed = ratio >= 0.25
    return GateResult(
        gate_name="validator::unnecessary_tool_use",
        gate_kind="validator",
        passed=passed,
        score=1.0 if passed else max(0.0, ratio),
        reason=(
            f"tool linkage ratio={ratio:.2f}"
            if passed
            else f"low concern linkage on tools ({linked}/{len(tools)})"
        ),
        evidence={"tool_calls": len(tools), "linked": linked},
        weight=0.4,
    )
