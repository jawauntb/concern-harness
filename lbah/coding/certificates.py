"""Bridge coding finish into LoadBearingCertificate."""

from __future__ import annotations

from typing import Any

from ..core.certificates import make_certificate
from ..core.schemas import (
    ActionProposal,
    CommitmentSurface,
    ConcernLedger,
    ConcernVariable,
    GateResult,
    LoadBearingCertificate,
    TaskSpec,
)
from ..validators import tool_validators
from .actions import CodingAction, CodingTask
from .events import CodingEventLog
from .ledger import CodingLedger
from .verifier import CodingCheckResult


def task_to_spec(task: CodingTask) -> TaskSpec:
    return TaskSpec(
        task_id=task.task_id,
        task_type="coding",
        instruction=task.instruction,
        success_criteria=list(task.success_criteria),
        known_proxy_risks=list(task.known_risks),
        max_steps=task.max_steps,
        metadata={
            **dict(task.metadata or {}),
            "repo_path": task.repo_path,
            "allowed_paths": list(task.allowed_paths),
            "test_commands": list(task.test_commands),
        },
    )


def ledger_to_concern_ledger(task: CodingTask, ledger: CodingLedger) -> ConcernLedger:
    spec = task_to_spec(task)
    variables = [
        ConcernVariable(
            id=c.id,
            name=c.id,
            value=c.text,
            concern=c.concern,
            source=c.kind,
            required_surfaces=["code_diff"],
            proxy_risks=["output_fabrication", "result_ignore"],
        )
        for c in ledger.concerns
    ]
    surfaces = [
        CommitmentSurface(
            id="code_diff",
            name="code diff",
            type="code_diff",
            validators=["result_ignore", "output_fabrication", "tool_skip", "unnecessary_tool_use"],
        )
    ]
    return ConcernLedger(task=spec, variables=variables, surfaces=surfaces)


def finish_action_to_proposal(
    action: CodingAction | None,
    *,
    final_diff: str,
    modified_files: list[str],
) -> ActionProposal:
    payload = {
        "diff": final_diff,
        "modified_files": list(modified_files),
    }
    if action is not None:
        payload = {**dict(action.payload or {}), **payload}
    return ActionProposal(
        action_id=action.action_id if action else "finish",
        surface_id="code_diff",
        action_type="finish",
        payload=payload,
        rationale=action.rationale if action else None,
        claimed_variables_used=list(action.concerns_addressed) if action else [],
    )


def checks_to_gates(checks: list[CodingCheckResult]) -> list[GateResult]:
    return [
        GateResult(
            gate_name=f"validator::{check.name}",
            gate_kind="validator",
            passed=check.passed,
            score=1.0 if check.passed else 0.0,
            reason=check.reason,
            evidence=dict(check.evidence or {}),
            weight=float(check.weight),
        )
        for check in checks
    ]


def run_tool_failure_gates(
    *,
    task: CodingTask,
    ledger: CodingLedger,
    trace: list[dict[str, Any]],
    final_diff: str,
    modified_files: list[str],
    action: CodingAction | None = None,
) -> tuple[list[GateResult], list[GateResult], list[GateResult]]:
    """ToolFailBench/ToolScan categories as transport/proxy/validator gates."""
    concern_ledger = ledger_to_concern_ledger(task, ledger)
    proposal = finish_action_to_proposal(
        action, final_diff=final_diff, modified_files=modified_files
    )
    # State.scratch carries the coding trace for the validators.
    from ..core.schemas import State

    state = State(
        task_id=task.task_id,
        scratch={
            "coding_trace": trace,
            "final_diff": final_diff,
            "modified_files": modified_files,
            "coding_ledger": ledger.model_dump(),
        },
    )
    transport = [tool_validators.result_ignore(proposal, concern_ledger, state, None)]
    proxy = [tool_validators.output_fabrication(proposal, concern_ledger, state, None)]
    validators = [
        tool_validators.tool_skip(proposal, concern_ledger, state, None),
        tool_validators.unnecessary_tool_use(proposal, concern_ledger, state, None),
    ]
    return transport, proxy, validators


def make_finish_certificate(
    *,
    task: CodingTask,
    ledger: CodingLedger,
    checks: list[CodingCheckResult],
    trace: list[dict[str, Any]],
    final_diff: str,
    modified_files: list[str],
    action: CodingAction | None = None,
    event_log: CodingEventLog | None = None,
) -> LoadBearingCertificate:
    concern_ledger = ledger_to_concern_ledger(task, ledger)
    proposal = finish_action_to_proposal(
        action, final_diff=final_diff, modified_files=modified_files
    )
    transport, proxy, tool_validators_gates = run_tool_failure_gates(
        task=task,
        ledger=ledger,
        trace=trace,
        final_diff=final_diff,
        modified_files=modified_files,
        action=action,
    )
    validators = checks_to_gates(checks) + tool_validators_gates
    reopen: list[GateResult] = []
    if event_log is not None and event_log.events:
        reopen.append(
            GateResult(
                gate_name="reopen::event_log_present",
                gate_kind="reopen",
                passed=True,
                score=1.0,
                reason=f"coding event log has {len(event_log.events)} events",
                evidence={"n_events": len(event_log.events), "label": event_log.label},
                weight=0.1,
            )
        )
    return make_certificate(
        task=concern_ledger.task,
        ledger=concern_ledger,
        proposal=proposal,
        transport=transport,
        proxy=proxy,
        reopen=reopen,
        validators=validators,
        behavior_passed=all(c.passed for c in checks) if checks else False,
    )


def mirror_action(log: CodingEventLog, action: CodingAction, before: CodingLedger) -> None:
    """Append action + concern deltas after ``ledger.apply_action``."""
    log.append(
        "record_action",
        payload=action.model_dump(),
        source="runner",
    )
    after_ids = {c.id: c for c in before.concerns}
    # Caller should pass the ledger *after* mutation; re-read via project compare
    # is done in runner with before/after snapshots.
    _ = after_ids  # kept for clarity; runner uses mirror_ledger_delta


def mirror_ledger_delta(
    log: CodingEventLog,
    before: CodingLedger,
    after: CodingLedger,
    *,
    source: str,
) -> None:
    """Append declare/revise/set_status/add_evidence events for a ledger mutation."""
    before_map = {c.id: c for c in before.concerns}
    after_map = {c.id: c for c in after.concerns}
    for cid, concern in after_map.items():
        if cid not in before_map:
            log.append(
                "declare_concern",
                concern_id=cid,
                payload=concern.model_dump(),
                source=source,
            )
            continue
        prev = before_map[cid]
        if prev.model_dump() == concern.model_dump():
            continue
        if prev.status != concern.status:
            payload: dict[str, Any] = {"status": concern.status}
            new_evidence = [e for e in concern.evidence if e not in prev.evidence]
            if new_evidence:
                payload["evidence_item"] = new_evidence[-1]
            log.append("set_status", concern_id=cid, payload=payload, source=source)
        if (
            prev.kind != concern.kind
            or prev.text != concern.text
            or prev.concern != concern.concern
            or (
                concern.evidence != prev.evidence
                and prev.status == concern.status
            )
        ):
            log.append(
                "revise_concern",
                concern_id=cid,
                payload=concern.model_dump(),
                source=source,
            )
