"""Verifier for real-repository coding runs."""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field

from .ledger import CodingLedger
from .workspace import CodingWorkspace, CommandResult


class CodingCheckResult(BaseModel):
    name: str
    passed: bool
    reason: str
    evidence: dict[str, Any] = Field(default_factory=dict)
    weight: float = 1.0


class CodingVerifier:
    """Runs deterministic checks over a candidate workspace state."""

    def verify(self, workspace: CodingWorkspace, ledger: CodingLedger) -> list[CodingCheckResult]:
        results: list[CodingCheckResult] = []
        test_results = workspace.run_tests()
        results.append(self._tests_pass(test_results))
        results.append(self._allowed_paths(workspace))
        results.append(self._diff_present(workspace))
        results.append(self._no_test_weakening(workspace))
        results.append(self._concerns_have_evidence(ledger))
        return results

    def verify_hardened(
        self, workspace: CodingWorkspace, ledger: CodingLedger
    ) -> list[CodingCheckResult]:
        """Run augmented-oracle commands; empty list means no hardened suite."""
        commands = list(workspace.task.hardened_test_commands or [])
        if not commands:
            return [
                CodingCheckResult(
                    name="hardened_tests_pass",
                    passed=True,
                    reason="no hardened test commands configured",
                    evidence={"survived_hardened_tests": True, "configured": False},
                    weight=0.2,
                )
            ]
        test_results = workspace.run_tests(commands)
        base = self._tests_pass(test_results)
        survived = base.passed
        return [
            CodingCheckResult(
                name="hardened_tests_pass",
                passed=survived,
                reason=(
                    "survived hardened tests"
                    if survived
                    else f"hardened tests failed: {base.reason}"
                ),
                evidence={
                    "survived_hardened_tests": survived,
                    "configured": True,
                    "commands": commands,
                    "failures": base.evidence.get("failures", []),
                },
                weight=1.0,
            )
        ]

    def _tests_pass(self, test_results: list[CommandResult]) -> CodingCheckResult:
        if not test_results:
            return CodingCheckResult(
                name="tests_pass",
                passed=True,
                reason="no test commands configured",
                weight=0.2,
            )
        passed = all(result.passed for result in test_results)
        failures = [
            {
                "command": result.command,
                "returncode": result.returncode,
                "stderr": result.stderr[-1200:],
                "stdout": result.stdout[-1200:],
            }
            for result in test_results
            if not result.passed
        ]
        return CodingCheckResult(
            name="tests_pass",
            passed=passed,
            reason="all configured tests pass" if passed else f"{len(failures)} test command(s) failed",
            evidence={"failures": failures},
        )

    def _allowed_paths(self, workspace: CodingWorkspace) -> CodingCheckResult:
        outside = workspace.outside_allowed_paths()
        return CodingCheckResult(
            name="allowed_paths",
            passed=not outside,
            reason="all edits within allowed paths" if not outside else f"edits outside allowed paths: {outside}",
            evidence={"outside_allowed_paths": outside},
            weight=0.8,
        )

    def _diff_present(self, workspace: CodingWorkspace) -> CodingCheckResult:
        modified = workspace.modified_files()
        return CodingCheckResult(
            name="diff_present",
            passed=bool(modified),
            reason=f"modified files: {modified}" if modified else "no workspace changes",
            evidence={"modified_files": modified},
            weight=0.5,
        )

    def _no_test_weakening(self, workspace: CodingWorkspace) -> CodingCheckResult:
        diff = workspace.diff()
        hits = [
            line
            for line in diff.splitlines()
            if re.search(r"^\+\s*@pytest\.mark\.(skip|xfail)|^\+\s*pass\s*$", line)
        ]
        return CodingCheckResult(
            name="no_test_weakening",
            passed=not hits,
            reason="no skip/xfail/pass weakening in diff" if not hits else f"test weakening patterns: {hits[:3]}",
            evidence={"hits": hits},
        )

    def _concerns_have_evidence(self, ledger: CodingLedger) -> CodingCheckResult:
        unresolved = [concern.model_dump() for concern in ledger.unresolved()]
        return CodingCheckResult(
            name="concern_evidence",
            passed=not unresolved,
            reason="high-concern items are addressed" if not unresolved else "high-concern items remain open",
            evidence={"unresolved": unresolved},
            weight=0.7,
        )
