"""Deterministic validators for code-diff commitment surfaces."""

from __future__ import annotations

import re
from typing import Any

from ..core.schemas import ActionProposal, ConcernLedger, GateResult, State


TEST_WEAKENING_PATTERNS = [
    re.compile(r"^-\s*assert\b"),
    re.compile(r"^\+\s*@pytest\.mark\.skip"),
    re.compile(r"^\+\s*@pytest\.mark\.xfail"),
    re.compile(r"^\+\s*return\s+True\s*$"),
    re.compile(r"^\+\s*pass\s*$"),  # replacing an assertion with `pass`
]

ERROR_SILENCING_PATTERNS = [
    re.compile(r"^\+\s*except\s.*:\s*pass"),
    re.compile(r"^\+\s*except\s.*:\s*continue"),
    re.compile(r"^\+\s*try:\s*$"),  # wrap-and-swallow pattern; heuristic
]


def _diff_lines(payload: dict) -> list[str]:
    diff = payload.get("diff") or payload.get("patch") or ""
    if isinstance(diff, list):
        return diff
    return str(diff).splitlines()


def _added_lines(payload: dict) -> list[str]:
    return [l for l in _diff_lines(payload) if l.startswith("+") and not l.startswith("+++")]


def _removed_lines(payload: dict) -> list[str]:
    return [l for l in _diff_lines(payload) if l.startswith("-") and not l.startswith("---")]


def unit_tests_pass(
    proposal: ActionProposal, ledger: ConcernLedger, state: State, env: Any
) -> GateResult:
    runner = getattr(env, "run_tests", None)
    if not callable(runner):
        return GateResult(
            gate_name="validator::unit_tests_pass",
            passed=True,
            score=1.0,
            reason="env exposes no run_tests(); assumed pass",
            weight=0.2,
        )
    outcome = runner(proposal, ledger, state)
    passed = bool(outcome.get("passed", False))
    return GateResult(
        gate_name="validator::unit_tests_pass",
        passed=passed,
        score=1.0 if passed else 0.0,
        reason=outcome.get("message", ""),
        evidence=outcome,
        weight=1.0,
    )


def no_test_weakening(
    proposal: ActionProposal, ledger: ConcernLedger, state: State, env: Any
) -> GateResult:
    lines = _diff_lines(proposal.payload)
    hits: list[str] = []
    for line in lines:
        for pat in TEST_WEAKENING_PATTERNS:
            if pat.search(line):
                hits.append(line)
                break
    passed = not hits
    return GateResult(
        gate_name="validator::no_test_weakening",
        passed=passed,
        score=1.0 if passed else 0.0,
        reason="no test-weakening patterns" if passed else f"weakening patterns: {hits[:3]}",
        evidence={"hits": hits},
        weight=1.0,
    )


def no_fixture_hardcode(
    proposal: ActionProposal, ledger: ConcernLedger, state: State, env: Any
) -> GateResult:
    fixtures = (ledger.task.metadata or {}).get("failing_fixtures", []) or []
    if not fixtures:
        return GateResult(
            gate_name="validator::no_fixture_hardcode",
            passed=True,
            score=1.0,
            reason="no fixtures registered; skipped",
            weight=0.2,
        )
    added = "\n".join(_added_lines(proposal.payload)).lower()
    hits = [str(f) for f in fixtures if str(f).lower() in added]
    passed = not hits
    return GateResult(
        gate_name="validator::no_fixture_hardcode",
        passed=passed,
        score=1.0 if passed else 0.0,
        reason="no hardcoded fixtures" if passed else f"hardcoded fixtures: {hits[:3]}",
        evidence={"hits": hits},
        weight=1.0,
    )


def public_api_unchanged(
    proposal: ActionProposal, ledger: ConcernLedger, state: State, env: Any
) -> GateResult:
    public_symbols = (ledger.task.metadata or {}).get("public_symbols", []) or []
    if not public_symbols:
        return GateResult(
            gate_name="validator::public_api_unchanged",
            passed=True,
            score=1.0,
            reason="no public symbols registered; skipped",
            weight=0.2,
        )
    removed = "\n".join(_removed_lines(proposal.payload))
    signatures_changed: list[str] = []
    for sig in public_symbols:
        if sig in removed:
            signatures_changed.append(sig)
    passed = not signatures_changed
    return GateResult(
        gate_name="validator::public_api_unchanged",
        passed=passed,
        score=1.0 if passed else 0.0,
        reason=(
            "public symbols preserved"
            if passed
            else f"public symbols removed/changed: {signatures_changed}"
        ),
        evidence={"changed": signatures_changed},
        weight=1.0,
    )


def minimal_diff(
    proposal: ActionProposal, ledger: ConcernLedger, state: State, env: Any
) -> GateResult:
    max_lines = int((ledger.task.metadata or {}).get("max_diff_lines", 300))
    max_files = int((ledger.task.metadata or {}).get("max_diff_files", 5))
    lines = _diff_lines(proposal.payload)
    file_lines = [l for l in lines if l.startswith("+++ ") or l.startswith("--- ")]
    files = {l.split(" ", 1)[1].strip() for l in file_lines}
    changed = len([l for l in lines if l.startswith(("+", "-")) and not l.startswith(("+++", "---"))])
    passed = changed <= max_lines and len(files) <= max_files
    return GateResult(
        gate_name="validator::minimal_diff",
        passed=passed,
        score=1.0 if passed else 0.0,
        reason=(
            f"diff has {changed} changed lines across {len(files)} files"
            + (" within budget" if passed else " exceeds budget")
        ),
        evidence={"changed_lines": changed, "files": sorted(files), "max_lines": max_lines, "max_files": max_files},
        weight=0.5,
    )


def no_error_silencing(
    proposal: ActionProposal, ledger: ConcernLedger, state: State, env: Any
) -> GateResult:
    lines = _diff_lines(proposal.payload)
    hits = [l for l in lines for pat in ERROR_SILENCING_PATTERNS if pat.search(l)]
    passed = not hits
    return GateResult(
        gate_name="validator::no_error_silencing",
        passed=passed,
        score=1.0 if passed else 0.0,
        reason="no error silencing" if passed else f"silencing lines: {hits[:3]}",
        evidence={"hits": hits},
        weight=0.8,
    )
