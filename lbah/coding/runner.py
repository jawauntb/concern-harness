"""Verify-and-iterate runner for real coding tasks."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from .actions import CodingAction, CodingObservation, CodingTask
from .ledger import CodingLedger
from .verifier import CodingCheckResult, CodingVerifier
from .workspace import CodingWorkspace


class CodingRunResult(BaseModel):
    task_id: str
    agent: str
    success: bool
    steps: int
    final_diff: str
    modified_files: list[str]
    ledger: dict[str, Any]
    trace: list[dict[str, Any]] = Field(default_factory=list)
    checks: list[CodingCheckResult] = Field(default_factory=list)
    wall_time_seconds: float = 0.0


class CodingHarnessRunner:
    """Runs a coding agent until a verified patch or budget exhaustion."""

    def __init__(
        self,
        agent: Any,
        workspace: CodingWorkspace,
        verifier: CodingVerifier | None = None,
    ):
        self.agent = agent
        self.workspace = workspace
        self.verifier = verifier or CodingVerifier()

    def run(self, task: CodingTask) -> CodingRunResult:
        t0 = time.time()
        ledger = CodingLedger.from_task(task)
        trace: list[dict[str, Any]] = []
        last_observation: CodingObservation | None = None
        checks: list[CodingCheckResult] = []

        for step in range(task.max_steps):
            state = {
                "step": step,
                "last_observation": last_observation.model_dump() if last_observation else None,
                "workspace": self.workspace.inspect(),
                "ledger": ledger.to_agent_state(),
            }
            try:
                action = self._coerce_action(
                    self.agent.propose_action(state, ledger.to_agent_state()),
                    step,
                )
            except Exception as exc:
                observation = self._proposal_error(step, exc)
                ledger.apply_observation(observation)
                if hasattr(self.agent, "observe"):
                    self.agent.observe(observation.model_dump())
                trace.append(
                    {
                        "step": step,
                        "action": {
                            "action_id": observation.action_id,
                            "action_type": "invalid_action",
                            "payload": {},
                        },
                        "observation": observation.model_dump(),
                        "modified_files": self.workspace.modified_files(),
                    }
                )
                last_observation = observation
                continue
            ledger.apply_action(action)
            observation = self._execute(action, ledger)
            ledger.apply_observation(observation)
            if hasattr(self.agent, "observe"):
                self.agent.observe(observation.model_dump())

            trace.append(
                {
                    "step": step,
                    "action": action.model_dump(),
                    "observation": observation.model_dump(),
                    "modified_files": self.workspace.modified_files(),
                }
            )
            last_observation = observation

            if action.action_type == "finish":
                checks = [CodingCheckResult.model_validate(item) for item in observation.data.get("checks", [])]
                if observation.success:
                    return self._result(task, ledger, trace, checks, t0, success=True)

        checks = self.verifier.verify(self.workspace, ledger)
        return self._result(task, ledger, trace, checks, t0, success=all(check.passed for check in checks))

    def _execute(self, action: CodingAction, ledger: CodingLedger) -> CodingObservation:
        try:
            if action.action_type == "inspect":
                data = self.workspace.inspect()
                return self._ok(action, "workspace inspected", data)
            if action.action_type == "search":
                matches = self.workspace.search(
                    str(action.payload.get("pattern", "")),
                    glob=action.payload.get("glob"),
                    limit=int(action.payload.get("limit", 50)),
                )
                return self._ok(action, f"{len(matches)} match(es)", {"matches": matches})
            if action.action_type == "read_file":
                content = self.workspace.read_file(
                    str(action.payload["path"]),
                    start=int(action.payload.get("start", 1)),
                    limit=int(action.payload.get("limit", 200)),
                )
                return self._ok(action, f"read {action.payload['path']}", {"content": content})
            if action.action_type == "edit_file":
                diff = self.workspace.edit_file(
                    str(action.payload["path"]),
                    old=action.payload.get("old"),
                    new=action.payload.get("new"),
                    content=action.payload.get("content"),
                )
                return self._ok(action, f"edited {action.payload['path']}", {"diff": diff})
            if action.action_type == "run_command":
                result = self.workspace.run_command(action.payload["command"])
                return CodingObservation(
                    action_id=action.action_id,
                    action_type=action.action_type,
                    success=result.passed,
                    message=f"command exited {result.returncode}",
                    data={"result": result.model_dump()},
                )
            if action.action_type == "run_tests":
                commands = action.payload.get("commands")
                results = self.workspace.run_tests(commands)
                passed = all(result.passed for result in results)
                return CodingObservation(
                    action_id=action.action_id,
                    action_type=action.action_type,
                    success=passed,
                    message="tests passed" if passed else "tests failed",
                    data={"results": [result.model_dump() for result in results]},
                )
            if action.action_type == "finish":
                checks = self.verifier.verify(self.workspace, ledger)
                passed = all(check.passed for check in checks)
                return CodingObservation(
                    action_id=action.action_id,
                    action_type=action.action_type,
                    success=passed,
                    message="verified patch" if passed else self._feedback(checks),
                    data={"checks": [check.model_dump() for check in checks]},
                )
        except Exception as exc:
            return CodingObservation(
                action_id=action.action_id,
                action_type=action.action_type,
                success=False,
                message=f"{type(exc).__name__}: {exc}",
                data={},
            )
        raise ValueError(f"unsupported action type {action.action_type}")

    def _ok(self, action: CodingAction, message: str, data: dict[str, Any]) -> CodingObservation:
        return CodingObservation(
            action_id=action.action_id,
            action_type=action.action_type,
            success=True,
            message=message,
            data=data,
        )

    def _proposal_error(self, step: int, exc: Exception) -> CodingObservation:
        return CodingObservation(
            action_id=f"proposal_error_{step}",
            action_type="inspect",
            success=False,
            message=f"proposal_error: {type(exc).__name__}: {exc}",
            data={"error_type": type(exc).__name__},
        )

    def _feedback(self, checks: list[CodingCheckResult]) -> str:
        failed = [check for check in checks if not check.passed]
        if not failed:
            return "verification failed"
        return "verification failed: " + "; ".join(f"{check.name}: {check.reason}" for check in failed)

    def _coerce_action(self, raw: CodingAction | dict[str, Any], step: int) -> CodingAction:
        if isinstance(raw, CodingAction):
            return raw
        data = dict(raw)
        data.setdefault("action_id", f"action_{step}")
        return CodingAction.model_validate(data)

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
        final_checks = checks or self.verifier.verify(self.workspace, ledger)
        return CodingRunResult(
            task_id=task.task_id,
            agent=getattr(self.agent, "name", "coding_agent"),
            success=success,
            steps=len(trace),
            final_diff=self.workspace.diff(),
            modified_files=self.workspace.modified_files(),
            ledger=ledger.model_dump(),
            trace=trace,
            checks=final_checks,
            wall_time_seconds=time.time() - t0,
        )


def load_coding_task(path: str | Path, repo_path: str | None = None) -> CodingTask:
    import yaml

    data = yaml.safe_load(Path(path).read_text()) or {}
    if repo_path is not None:
        data["repo_path"] = repo_path
    return CodingTask.model_validate(data)
