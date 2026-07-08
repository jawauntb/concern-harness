"""Certificate assembly and decision logic."""

from __future__ import annotations

from .schemas import (
    ActionProposal,
    ConcernLedger,
    Decision,
    GateResult,
    LoadBearingCertificate,
    TaskSpec,
)


DEFAULT_THRESHOLDS = {
    "low_risk": 0.65,
    "normal": 0.45,
    "high_risk": 0.25,
    "irreversible": 0.15,
}


def _weighted_score(results: list[GateResult]) -> float:
    if not results:
        return 1.0
    total_w = sum(max(r.weight, 1e-9) for r in results)
    if total_w == 0:
        return 1.0
    return sum(r.score * max(r.weight, 1e-9) for r in results) / total_w


def _behavior_score(validators: list[GateResult]) -> float:
    if not validators:
        return 1.0
    passed = sum(1 for r in validators if r.passed)
    return passed / len(validators)


def compute_load_score(
    behavior: float,
    transport: float,
    proxy: float,
    reopen: float,
    validity: float,
) -> float:
    return behavior * transport * proxy * reopen * validity


def decide_from_gates(
    task: TaskSpec,
    ledger: ConcernLedger,
    proposal: ActionProposal,
    transport: list[GateResult],
    proxy: list[GateResult],
    reopen: list[GateResult],
    validators: list[GateResult],
    thresholds: dict[str, float] | None = None,
) -> Decision:
    """Turn gate results into a commitment decision."""
    th = {**DEFAULT_THRESHOLDS, **(thresholds or {})}

    behavior_score = _behavior_score(validators)
    transport_score = _weighted_score(transport)
    proxy_score = _weighted_score(proxy)
    reopen_score = _weighted_score(reopen)
    validity_score = _weighted_score(validators)
    load = compute_load_score(
        behavior_score,
        transport_score,
        proxy_score,
        reopen_score,
        validity_score,
    )

    surface = ledger.surface_by_id(proposal.surface_id)
    irreversible = task.irreversible or (surface.irreversible if surface else False)

    threshold = th["irreversible"] if irreversible else th["normal"]

    if any(not r.passed and r.weight >= 0.9 for r in reopen):
        return "reopen"
    if any(not r.passed for r in validators):
        return "revise"
    if any(not r.passed and r.weight >= 0.7 for r in proxy):
        return "revise"
    # Any failed transport of a variable with concern >= 0.7 is a revise.
    # The paper's transport obligation says a high-concern distinction MUST
    # survive to the commitment surface; a partial score is not enough.
    if any(not r.passed and r.weight >= 0.7 for r in transport):
        return "revise"
    if load < threshold:
        return "block"
    return "allow"


def make_certificate(
    task: TaskSpec,
    ledger: ConcernLedger,
    proposal: ActionProposal,
    transport: list[GateResult],
    proxy: list[GateResult],
    reopen: list[GateResult],
    validators: list[GateResult],
    thresholds: dict[str, float] | None = None,
    behavior_passed: bool | None = None,
) -> LoadBearingCertificate:
    behavior_score = _behavior_score(validators)
    transport_score = _weighted_score(transport)
    proxy_score = _weighted_score(proxy)
    reopen_score = _weighted_score(reopen)
    validity_score = _weighted_score(validators)
    load = compute_load_score(
        behavior_score,
        transport_score,
        proxy_score,
        reopen_score,
        validity_score,
    )
    decision = decide_from_gates(
        task,
        ledger,
        proposal,
        transport,
        proxy,
        reopen,
        validators,
        thresholds=thresholds,
    )

    failed = [
        r.gate_name
        for r in (transport + proxy + reopen + validators)
        if not r.passed
    ]
    summary = (
        f"{decision.upper()}: load={load:.2f} "
        f"behavior={behavior_score:.2f} transport={transport_score:.2f} "
        f"proxy={proxy_score:.2f} reopen={reopen_score:.2f}"
    )
    if failed:
        summary += f" failed={failed}"

    return LoadBearingCertificate(
        task_id=task.task_id,
        action_id=proposal.action_id,
        surface_id=proposal.surface_id,
        behavior_passed=behavior_passed if behavior_passed is not None
        else all(r.passed for r in validators),
        transport_results=transport,
        proxy_results=proxy,
        reopenability_results=reopen,
        validator_results=validators,
        load_score=load,
        behavior_score=behavior_score,
        transport_score=transport_score,
        proxy_resistance_score=proxy_score,
        reopenability_score=reopen_score,
        commitment_validity_score=validity_score,
        decision=decision,
        summary=summary,
    )
