"""Bounded recursive child harnessing for LBAH-Code."""

from __future__ import annotations

import time
from typing import Any

from pydantic import ValidationError

from .actions import CodingObservation, CodingTask
from .ledger import CodingConcern, CodingLedger
from .runner import CodingHarnessRunner, CodingRunResult
from .task_tree import ChildTaskResult, ChildTaskSpec, default_child_tasks
from .verifier import CodingCheckResult, CodingVerifier
from .workspace import CodingWorkspace


class ScriptedChildAgent:
    """Deterministic child-role agent for tests and reproducible demos."""

    def __init__(self, results: list[ChildTaskResult], name: str = "scripted_child_agent"):
        self.name = name
        self.results = list(results)
        self.calls: list[dict[str, Any]] = []

    def run_child(
        self,
        spec: ChildTaskSpec,
        state: dict[str, Any],
        ledger: dict[str, Any],
    ) -> ChildTaskResult:
        self.calls.append({"spec": spec.model_dump(), "state": state, "ledger": ledger})
        if not self.results:
            return ChildTaskResult(
                child_id=spec.child_id,
                role=spec.role,
                status="skipped",
                summary="script exhausted before this child role ran",
                confidence=0.0,
            )
        return self.results.pop(0)


class RecursiveCodingHarnessRunner:
    """Runs child roles first, validates them, then starts the parent loop."""

    def __init__(
        self,
        agent: Any,
        workspace: CodingWorkspace,
        child_agent: Any,
        verifier: CodingVerifier | None = None,
        *,
        child_tasks: list[ChildTaskSpec] | None = None,
        fail_fast_on_child_error: bool = True,
    ):
        self.agent = agent
        self.workspace = workspace
        self.child_agent = child_agent
        self.verifier = verifier or CodingVerifier()
        self.child_tasks = child_tasks
        self.fail_fast_on_child_error = fail_fast_on_child_error

    def run(self, task: CodingTask) -> CodingRunResult:
        t0 = time.time()
        ledger = CodingLedger.from_task(task)
        trace: list[dict[str, Any]] = []
        child_results: list[ChildTaskResult] = []
        child_checks: list[CodingCheckResult] = []

        child_tasks = self.child_tasks if self.child_tasks is not None else default_child_tasks(task)
        for index, spec in enumerate(child_tasks):
            result = self._coerce_child_result(
                self.child_agent.run_child(
                    spec,
                    self._child_state(task, index, ledger),
                    ledger.to_agent_state(),
                )
            )
            check = validate_child_result(spec, result)
            child_checks.append(check)
            trace.append(self._child_trace(index, spec, result, check))

            if check.passed:
                apply_child_result(ledger, result)
                child_results.append(result)
            elif self.fail_fast_on_child_error:
                return self._result(
                    task,
                    ledger,
                    trace,
                    child_checks,
                    t0,
                    success=False,
                )

        if not all(check.passed for check in child_checks):
            return self._result(
                task,
                ledger,
                trace,
                child_checks,
                t0,
                success=False,
            )

        summary = CodingObservation(
            action_id="recursive_children",
            action_type="inspect",
            success=True,
            message=f"{len(child_results)} recursive child task(s) completed",
            data={
                "recursive_children": [
                    result.model_dump() for result in child_results
                ],
                "child_checks": [check.model_dump() for check in child_checks],
            },
        )
        trace.append(
            {
                "step": "recursive_summary",
                "action": {
                    "action_id": summary.action_id,
                    "action_type": "recursive_summary",
                    "payload": {},
                },
                "observation": summary.model_dump(),
                "modified_files": self.workspace.modified_files(),
            }
        )

        runner = CodingHarnessRunner(self.agent, self.workspace, self.verifier)
        return runner.run_with_ledger(
            task,
            ledger,
            initial_observation=summary,
            initial_trace=trace,
            started_at=t0,
        )

    def _child_state(
        self,
        task: CodingTask,
        index: int,
        ledger: CodingLedger,
    ) -> dict[str, Any]:
        return {
            "task": task.model_dump(),
            "child_index": index,
            "workspace": self.workspace.inspect(),
            "ledger": ledger.to_agent_state(),
        }

    def _coerce_child_result(self, raw: ChildTaskResult | dict[str, Any]) -> ChildTaskResult:
        if isinstance(raw, ChildTaskResult):
            return raw
        return ChildTaskResult.model_validate(raw)

    def _child_trace(
        self,
        index: int,
        spec: ChildTaskSpec,
        result: ChildTaskResult,
        check: CodingCheckResult,
    ) -> dict[str, Any]:
        return {
            "step": f"recursive_child_{index}",
            "action": {
                "action_id": spec.child_id,
                "action_type": "recursive_child",
                "payload": spec.model_dump(),
            },
            "observation": {
                "action_id": spec.child_id,
                "action_type": "recursive_child",
                "success": check.passed,
                "message": check.reason,
                "data": {
                    "child_result": result.model_dump(),
                    "child_check": check.model_dump(),
                },
            },
            "modified_files": self.workspace.modified_files(),
        }

    def _result(
        self,
        task: CodingTask,
        ledger: CodingLedger,
        trace: list[dict[str, Any]],
        checks: list[CodingCheckResult],
        t0: float,
        *,
        success: bool,
    ) -> CodingRunResult:
        return CodingRunResult(
            task_id=task.task_id,
            agent=getattr(self.agent, "name", "coding_agent"),
            success=success,
            steps=len(trace),
            final_diff=self.workspace.diff(),
            modified_files=self.workspace.modified_files(),
            ledger=ledger.model_dump(),
            trace=trace,
            checks=checks,
            wall_time_seconds=time.time() - t0,
        )


def validate_child_result(
    spec: ChildTaskSpec,
    result: ChildTaskResult,
) -> CodingCheckResult:
    """Validate that a child output is useful enough to guide the parent."""

    errors: list[str] = []
    if result.child_id != spec.child_id:
        errors.append(f"child_id mismatch: expected {spec.child_id}, got {result.child_id}")
    if result.role != spec.role:
        errors.append(f"role mismatch: expected {spec.role}, got {result.role}")
    if result.status != "passed":
        errors.append(f"child status is {result.status}")
    for required in spec.evidence_required:
        if not _evidence_contains(result, required):
            errors.append(f"missing required evidence: {required}")
    for index, action in enumerate(result.proposed_actions):
        if not action.rationale:
            errors.append(f"proposed action {index} is missing rationale")
        if not action.concerns_addressed and not action.ledger_updates:
            errors.append(f"proposed action {index} has no concern linkage")
    for index, update in enumerate(result.ledger_updates):
        try:
            CodingConcern.model_validate(update)
        except ValidationError as exc:
            errors.append(f"ledger update {index} is invalid: {exc.errors()[0]['msg']}")

    return CodingCheckResult(
        name=f"recursive_child_{spec.child_id}",
        passed=not errors,
        reason="child output validated" if not errors else "; ".join(errors),
        evidence={
            "spec": spec.model_dump(),
            "result": result.model_dump(),
        },
        weight=0.8,
    )


def apply_child_result(ledger: CodingLedger, result: ChildTaskResult) -> None:
    """Reduce validated child output into the parent concern ledger."""

    observation = CodingObservation(
        action_id=f"child_{result.child_id}",
        action_type="inspect",
        success=True,
        message=f"{result.role} passed: {result.summary}",
        data={"child_result": result.model_dump()},
    )
    ledger.apply_observation(observation)
    for update in result.ledger_updates:
        ledger.append_concern(CodingConcern.model_validate(update))
    for index, evidence in enumerate(result.evidence):
        ledger.append_concern(
            CodingConcern(
                id=f"child_{result.child_id}_evidence_{index}",
                kind="evidence",
                text=evidence,
                concern=0.6,
                status="addressed",
                evidence=[result.summary],
            )
        )


def _evidence_contains(result: ChildTaskResult, needle: str) -> bool:
    haystack = [result.summary, *result.evidence]
    return any(needle.lower() in item.lower() for item in haystack)
