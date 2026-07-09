"""Candidate patch tournaments for LBAH-Code."""

from __future__ import annotations

import shutil
import tempfile
import time
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError

from .actions import CodingTask
from .events import CodingEventLog, events_from_ledger
from .ledger import CodingLedger
from .runner import CodingHarnessRunner, CodingRunResult
from .verifier import CodingCheckResult, CodingVerifier
from .workspace import CodingWorkspace


class CandidateScore(BaseModel):
    """Score components used to rank candidate patches."""

    score: float
    base_score: float
    check_score: float
    concern_coverage: float
    diff_focus: float
    tests_passed: bool
    review_penalty: float = 0.0
    reasons: list[str] = Field(default_factory=list)


ReviewSeverity = Literal["blocker", "major", "minor", "info"]
ReviewStatus = Literal["open", "addressed", "rejected"]
REVIEW_SEVERITY_PENALTIES: dict[ReviewSeverity, float] = {
    "blocker": 1.0,
    "major": 0.35,
    "minor": 0.15,
    "info": 0.0,
}


class CandidateReviewSignal(BaseModel):
    """Reviewer or adversarial signal used to down-rank risky candidates."""

    reviewer: str = "reviewer"
    severity: ReviewSeverity = "major"
    status: ReviewStatus = "open"
    summary: str
    evidence: list[str] = Field(default_factory=list)
    penalty: float | None = Field(default=None, ge=0.0, le=1.0)


class CandidateRun(BaseModel):
    """One isolated candidate patch attempt."""

    candidate_id: str
    ordinal: int
    agent: str
    result: CodingRunResult
    score: CandidateScore
    review_signals: list[CandidateReviewSignal] = Field(default_factory=list)
    selected: bool = False
    event_log: dict[str, Any] | None = None


class TournamentRunResult(BaseModel):
    """Result of generating, scoring, selecting, and applying candidates."""

    task_id: str
    success: bool
    winner_id: str | None
    applied_result: CodingRunResult | None = None
    candidates: list[CandidateRun] = Field(default_factory=list)
    final_diff: str = ""
    modified_files: list[str] = Field(default_factory=list)
    trace: list[dict[str, Any]] = Field(default_factory=list)
    wall_time_seconds: float = 0.0
    event_log: dict[str, Any] | None = None


class CandidatePatchTournamentRunner:
    """Runs candidate agents in isolated repo copies and applies the winner."""

    def __init__(
        self,
        candidate_agents: list[Any],
        workspace: CodingWorkspace,
        verifier: CodingVerifier | None = None,
    ):
        if not candidate_agents:
            raise ValueError("candidate patch tournament requires at least one agent")
        self.candidate_agents = candidate_agents
        self.workspace = workspace
        self.verifier = verifier or CodingVerifier()

    def run(self, task: CodingTask) -> TournamentRunResult:
        t0 = time.time()
        candidates: list[CandidateRun] = []
        trace: list[dict[str, Any]] = []
        root_log = events_from_ledger(CodingLedger.from_task(task))
        root_log.append(
            "note",
            payload={"kind": "tournament_start", "n_candidates": len(self.candidate_agents)},
            source="tournament",
        )
        parent_seq = root_log.events[-1].seq if root_log.events else 0

        with tempfile.TemporaryDirectory(prefix="lbah-candidates-") as tmp:
            for index, agent in enumerate(self.candidate_agents):
                candidate_id = f"candidate_{index}"
                candidate_root = Path(tmp) / candidate_id
                self._copy_workspace(candidate_root)
                branch = root_log.fork_at(parent_seq, label=candidate_id)
                branch.append(
                    "fork_workspace",
                    payload={
                        "candidate_id": candidate_id,
                        "repo_path": str(candidate_root),
                        "agent": getattr(agent, "name", "coding_agent"),
                    },
                    source="tournament",
                )
                candidate_task = task.model_copy(update={"repo_path": str(candidate_root)})
                candidate_workspace = CodingWorkspace(
                    candidate_root,
                    candidate_task,
                    timeout_seconds=self.workspace.timeout_seconds,
                )
                result = CodingHarnessRunner(agent, candidate_workspace, self.verifier).run(
                    candidate_task
                )
                # Merge candidate run lineage under the fork label.
                if result.event_log:
                    child = CodingEventLog.model_validate(result.event_log)
                    for event in child.events:
                        if event.type == "declare_concern" and any(
                            e.concern_id == event.concern_id and e.type == "declare_concern"
                            for e in branch.events
                        ):
                            continue
                        branch.append(
                            event.type,
                            concern_id=event.concern_id,
                            payload=event.payload,
                            source=event.source or candidate_id,
                        )
                review_signals = extract_candidate_review_signals(result)
                score = score_candidate_result(result, review_signals)
                candidate = CandidateRun(
                    candidate_id=candidate_id,
                    ordinal=index,
                    agent=getattr(agent, "name", "coding_agent"),
                    result=result,
                    score=score,
                    review_signals=review_signals,
                    event_log=branch.model_dump(),
                )
                candidates.append(candidate)
                root_log.append(
                    "note",
                    payload={
                        "kind": "candidate_finished",
                        "candidate_id": candidate_id,
                        "success": result.success,
                        "score": score.score,
                        "n_events": len(branch.events),
                    },
                    source="tournament",
                )
                trace.append(
                    {
                        "step": candidate_id,
                        "agent": candidate.agent,
                        "success": result.success,
                        "score": score.model_dump(),
                        "modified_files": result.modified_files,
                        "lineage_label": candidate_id,
                    }
                )

            winner = select_winning_candidate(candidates)
            if winner is None:
                return self._result(
                    task, False, None, None, candidates, trace, t0, event_log=root_log
                )

            winner.selected = True
            root_log.append(
                "note",
                payload={"kind": "winner_selected", "candidate_id": winner.candidate_id},
                source="tournament",
            )
            winner_root = Path(tmp) / winner.candidate_id
            self._apply_candidate_files(winner_root, winner.result.modified_files)
            applied_result = self._applied_result(task, winner, trace, t0)
            return self._result(
                task,
                applied_result.success,
                winner.candidate_id,
                applied_result,
                candidates,
                trace,
                t0,
                event_log=root_log,
            )

    def _copy_workspace(self, destination: Path) -> None:
        shutil.copytree(
            self.workspace.root,
            destination,
            ignore=shutil.ignore_patterns(".git", ".pytest_cache", "__pycache__"),
        )

    def _apply_candidate_files(self, source_root: Path, modified_files: list[str]) -> None:
        for rel_path in modified_files:
            source = source_root / rel_path
            if source.exists():
                self.workspace.edit_file(rel_path, content=source.read_text())
                continue
            target = self._target_path(rel_path)
            if target.exists():
                target.unlink()

    def _target_path(self, rel_path: str) -> Path:
        target = (self.workspace.root / rel_path).resolve()
        if target != self.workspace.root and self.workspace.root not in target.parents:
            raise ValueError(f"path escapes workspace: {rel_path}")
        return target

    def _applied_result(
        self,
        task: CodingTask,
        winner: CandidateRun,
        trace: list[dict[str, Any]],
        t0: float,
    ) -> CodingRunResult:
        ledger = CodingLedger.model_validate(winner.result.ledger)
        checks = self.verifier.verify(self.workspace, ledger)
        return CodingRunResult(
            task_id=task.task_id,
            agent=f"tournament:{winner.agent}",
            success=all(check.passed for check in checks),
            steps=winner.result.steps,
            final_diff=self.workspace.diff(),
            modified_files=self.workspace.modified_files(),
            ledger=ledger.model_dump(),
            trace=trace,
            checks=checks,
            wall_time_seconds=time.time() - t0,
            certificates=list(winner.result.certificates),
            event_log=winner.event_log or winner.result.event_log,
            load_score=winner.result.load_score,
        )

    def _result(
        self,
        task: CodingTask,
        success: bool,
        winner_id: str | None,
        applied_result: CodingRunResult | None,
        candidates: list[CandidateRun],
        trace: list[dict[str, Any]],
        t0: float,
        *,
        event_log: CodingEventLog | None = None,
    ) -> TournamentRunResult:
        return TournamentRunResult(
            task_id=task.task_id,
            success=success,
            winner_id=winner_id,
            applied_result=applied_result,
            candidates=candidates,
            final_diff=self.workspace.diff(),
            modified_files=self.workspace.modified_files(),
            trace=trace,
            wall_time_seconds=time.time() - t0,
            event_log=event_log.model_dump() if event_log is not None else None,
        )


def score_candidate_result(
    result: CodingRunResult,
    review_signals: list[CandidateReviewSignal] | None = None,
) -> CandidateScore:
    checks = result.checks
    total_weight = sum(check.weight for check in checks) or 1.0
    passed_weight = sum(check.weight for check in checks if check.passed)
    check_score = passed_weight / total_weight
    concern_coverage = _concern_coverage(result)
    diff_focus = _diff_focus(result)
    tests_passed = _tests_passed(checks)
    base_score = (
        0.55 * check_score
        + 0.25 * concern_coverage
        + 0.15 * diff_focus
        + 0.05 * (1.0 if result.final_diff else 0.0)
    )
    review_penalty = _review_penalty(review_signals or [])
    score = max(0.0, base_score - review_penalty)
    reasons = [
        f"checks={check_score:.2f}",
        f"concerns={concern_coverage:.2f}",
        f"focus={diff_focus:.2f}",
    ]
    if review_penalty:
        reasons.append(f"review_penalty={review_penalty:.2f}")
    if tests_passed:
        reasons.append("tests passed")
    if result.success:
        reasons.append("verified")
    return CandidateScore(
        score=score,
        base_score=base_score,
        check_score=check_score,
        concern_coverage=concern_coverage,
        diff_focus=diff_focus,
        tests_passed=tests_passed,
        review_penalty=review_penalty,
        reasons=reasons,
    )


def select_winning_candidate(candidates: list[CandidateRun]) -> CandidateRun | None:
    verified = [candidate for candidate in candidates if candidate.result.success]
    if not verified:
        return None
    return sorted(
        verified,
        key=lambda candidate: (
            -candidate.score.score,
            not candidate.score.tests_passed,
            len(candidate.result.modified_files),
            candidate.ordinal,
        ),
    )[0]


def _concern_coverage(result: CodingRunResult) -> float:
    concerns = [
        concern
        for concern in result.ledger.get("concerns", [])
        if float(concern.get("concern", 0.0)) >= 0.7
    ]
    if not concerns:
        return 1.0
    covered = [
        concern
        for concern in concerns
        if concern.get("status") != "open" or concern.get("evidence")
    ]
    return len(covered) / len(concerns)


def extract_candidate_review_signals(result: CodingRunResult) -> list[CandidateReviewSignal]:
    """Extract review signals embedded in candidate action/observation trace."""

    signals: list[CandidateReviewSignal] = []
    for entry in result.trace:
        action = entry.get("action", {})
        observation = entry.get("observation", {})
        for raw in _raw_review_signals(action):
            signals.append(_coerce_review_signal(raw))
        data = observation.get("data", {}) if isinstance(observation, dict) else {}
        for raw in _raw_review_signals(data):
            signals.append(_coerce_review_signal(raw))
    return signals


def _raw_review_signals(container: Any) -> list[Any]:
    if not isinstance(container, dict):
        return []
    raw = container.get("review_signals")
    return raw if isinstance(raw, list) else []


def _coerce_review_signal(raw: Any) -> CandidateReviewSignal:
    try:
        return CandidateReviewSignal.model_validate(raw)
    except ValidationError as exc:
        return CandidateReviewSignal(
            reviewer="review_signal_parser",
            severity="major",
            summary=f"invalid review signal: {exc.errors()[0]['msg']}",
            evidence=[repr(raw)[:500]],
        )


def _review_penalty(signals: list[CandidateReviewSignal]) -> float:
    penalty = 0.0
    for signal in signals:
        if signal.status != "open":
            continue
        penalty += signal.penalty if signal.penalty is not None else REVIEW_SEVERITY_PENALTIES[signal.severity]
    return min(1.0, penalty)


def _diff_focus(result: CodingRunResult) -> float:
    allowed_check = next((check for check in result.checks if check.name == "allowed_paths"), None)
    if allowed_check is not None and not allowed_check.passed:
        return 0.0
    if not result.modified_files:
        return 0.0
    return 1.0 / max(1, len(result.modified_files))


def _tests_passed(checks: list[CodingCheckResult]) -> bool:
    tests_check = next((check for check in checks if check.name == "tests_pass"), None)
    return bool(tests_check and tests_check.passed)
