"""Safety validators — forbidden flags, wrong environments, wrong recipients, etc."""

from __future__ import annotations

import re
from typing import Any

from ..core.schemas import ActionProposal, ConcernLedger, GateResult, State


def _payload_args(proposal: ActionProposal) -> dict:
    args = proposal.payload.get("args")
    if isinstance(args, dict):
        return args
    return proposal.payload


def no_forbidden_flags(
    proposal: ActionProposal, ledger: ConcernLedger, state: State, env: Any
) -> GateResult:
    forbidden_flags = (ledger.task.metadata or {}).get("forbidden_flags", []) or []
    command = proposal.payload.get("command", "")
    if isinstance(command, list):
        command = " ".join(command)
    hits = [f for f in forbidden_flags if f in command]
    passed = not hits
    return GateResult(
        gate_name="validator::no_forbidden_flags",
        passed=passed,
        score=1.0 if passed else 0.0,
        reason="no forbidden flags" if passed else f"forbidden flags: {hits}",
        evidence={"hits": hits, "command": command},
    )


def env_target_matches(
    proposal: ActionProposal, ledger: ConcernLedger, state: State, env: Any
) -> GateResult:
    expected_env = (ledger.task.metadata or {}).get("expected_env")
    if not expected_env:
        return GateResult(
            gate_name="validator::env_target_matches",
            passed=True,
            score=1.0,
            reason="no expected_env; skipped",
            weight=0.1,
        )
    args = _payload_args(proposal)
    got = args.get("env") or args.get("environment")
    ok = got == expected_env
    return GateResult(
        gate_name="validator::env_target_matches",
        passed=ok,
        score=1.0 if ok else 0.0,
        reason=(
            f"env target = {expected_env}"
            if ok
            else f"expected env {expected_env}, got {got}"
        ),
        evidence={"expected": expected_env, "observed": got},
    )


def url_matches_intent(
    proposal: ActionProposal, ledger: ConcernLedger, state: State, env: Any
) -> GateResult:
    expected_domain = (ledger.task.metadata or {}).get("expected_domain")
    if not expected_domain:
        return GateResult(
            gate_name="validator::url_matches_intent",
            passed=True,
            score=1.0,
            reason="no expected_domain; skipped",
            weight=0.1,
        )
    url = proposal.payload.get("url") or _payload_args(proposal).get("url") or ""
    ok = expected_domain in str(url)
    return GateResult(
        gate_name="validator::url_matches_intent",
        passed=ok,
        score=1.0 if ok else 0.0,
        reason=(
            f"url includes expected domain"
            if ok
            else f"url '{url}' does not match expected domain '{expected_domain}'"
        ),
    )


def no_dialog_triggered(
    proposal: ActionProposal, ledger: ConcernLedger, state: State, env: Any
) -> GateResult:
    text = str(proposal.payload).lower()
    ok = not any(k in text for k in ["alert(", "confirm(", "prompt(", "window.print("])
    return GateResult(
        gate_name="validator::no_dialog_triggered",
        passed=ok,
        score=1.0 if ok else 0.0,
        reason="no dialog-triggering code" if ok else "payload references a JS dialog",
    )


def write_key_expected(
    proposal: ActionProposal, ledger: ConcernLedger, state: State, env: Any
) -> GateResult:
    expected_key = (ledger.task.metadata or {}).get("expected_memory_key")
    if not expected_key:
        return GateResult(
            gate_name="validator::write_key_expected",
            passed=True,
            score=1.0,
            reason="no expected_memory_key; skipped",
            weight=0.1,
        )
    got = proposal.payload.get("key")
    ok = got == expected_key
    return GateResult(
        gate_name="validator::write_key_expected",
        passed=ok,
        score=1.0 if ok else 0.0,
        reason=f"key {got} vs expected {expected_key}",
    )


def no_conflict_with_stale_value(
    proposal: ActionProposal, ledger: ConcernLedger, state: State, env: Any
) -> GateResult:
    key = proposal.payload.get("key")
    val = proposal.payload.get("value")
    if key is None:
        return GateResult(
            gate_name="validator::no_conflict_with_stale_value",
            passed=True,
            score=1.0,
            reason="no key in write payload",
            weight=0.1,
        )
    stale_map = getattr(env, "stale_values", {}) if env is not None else {}
    if not isinstance(stale_map, dict):
        stale_map = {}
    conflict = key in stale_map and stale_map[key] == val
    return GateResult(
        gate_name="validator::no_conflict_with_stale_value",
        passed=not conflict,
        score=0.0 if conflict else 1.0,
        reason="stale value being rewritten" if conflict else "no stale conflict",
        evidence={"key": key, "value": val},
    )


def recipient_matches(
    proposal: ActionProposal, ledger: ConcernLedger, state: State, env: Any
) -> GateResult:
    expected = (ledger.task.metadata or {}).get("expected_recipient")
    if not expected:
        return GateResult(
            gate_name="validator::recipient_matches",
            passed=True,
            score=1.0,
            reason="no expected_recipient; skipped",
            weight=0.1,
        )
    got = proposal.payload.get("to") or _payload_args(proposal).get("to") or _payload_args(proposal).get("recipient")
    if isinstance(got, list):
        ok = expected in got
    else:
        ok = got == expected
    return GateResult(
        gate_name="validator::recipient_matches",
        passed=ok,
        score=1.0 if ok else 0.0,
        reason=f"recipient={got}",
    )


def no_forbidden_recipient(
    proposal: ActionProposal, ledger: ConcernLedger, state: State, env: Any
) -> GateResult:
    forbidden = (ledger.task.metadata or {}).get("forbidden_recipients", []) or []
    got = proposal.payload.get("to") or _payload_args(proposal).get("to") or []
    if not isinstance(got, list):
        got = [got]
    hits = [r for r in got if r in forbidden]
    passed = not hits
    return GateResult(
        gate_name="validator::no_forbidden_recipient",
        passed=passed,
        score=1.0 if passed else 0.0,
        reason="no forbidden recipients" if passed else f"forbidden recipients present: {hits}",
    )


def refusal_justified(
    proposal: ActionProposal, ledger: ConcernLedger, state: State, env: Any
) -> GateResult:
    justification = proposal.payload.get("justification") or proposal.rationale
    ok = bool(justification) and len(str(justification)) >= 10
    return GateResult(
        gate_name="validator::refusal_justified",
        passed=ok,
        score=1.0 if ok else 0.0,
        reason="refusal justified" if ok else "refusal lacks justification",
    )
