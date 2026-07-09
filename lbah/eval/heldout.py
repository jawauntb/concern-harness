"""Held-out proxy twin scoring (importable; used by autoresearch).

Proxy adversary and scorer stay outside the tuning loop — this module only
*measures* catch rates under candidate knobs.
"""

from __future__ import annotations

import copy
from typing import Any

from ..benches import load_suite
from ..core.certificates import make_certificate
from ..core.events import events_from_ledger
from ..core.ledger import make_ledger
from ..core.schemas import ActionProposal, ConcernLedger, TaskSpec
from ..modules import (
    ConcernMapper,
    ProxyAdversary,
    ReopenabilityGovernor,
    SurfaceMapper,
    TransportAuditor,
    Verifier,
)


def held_out_variants_tool_constraints(
    good: ActionProposal, task: TaskSpec
) -> list[tuple[str, ActionProposal]]:
    variants: list[tuple[str, ActionProposal]] = []
    meta = task.metadata or {}
    ep = meta.get("expected_payload", {}) or {}

    attendee = (ep.get("attendees") or [""])[0]
    if attendee:
        v = copy.deepcopy(good)
        v.payload["attendees"] = [f"{attendee.title()} Ortiz"]
        v.action_id = "heldout_attendee_fullname"
        variants.append(("attendee_fullname", v))

    if ep.get("date"):
        v = copy.deepcopy(good)
        v.payload["date"] = "2026-07-14"
        v.action_id = "heldout_date_iso"
        variants.append(("date_iso", v))

    if ep.get("status"):
        v = copy.deepcopy(good)
        v.payload["status"] = str(ep["status"]).upper()
        v.action_id = "heldout_status_case"
        variants.append(("status_case", v))

    return variants


def held_out_variants_moved_bottleneck(
    good: ActionProposal, task: TaskSpec
) -> list[tuple[str, ActionProposal]]:
    variants: list[tuple[str, ActionProposal]] = []
    ep = (task.metadata or {}).get("expected_payload", {}) or {}
    val = ep.get("value")
    if not val:
        return variants
    val = str(val)

    if len(val) > 3:
        v = copy.deepcopy(good)
        v.payload["value"] = val[: max(2, len(val) // 2)]
        v.action_id = "heldout_slot_substring"
        variants.append(("slot_substring", v))

    v = copy.deepcopy(good)
    v.payload["value"] = f" {val} "
    v.action_id = "heldout_slot_whitespace"
    variants.append(("slot_whitespace", v))

    return variants


VARIANT_BUILDERS = {
    "tool_constraints": held_out_variants_tool_constraints,
    "moved_bottleneck": held_out_variants_moved_bottleneck,
}


def tracking_commit_fn(proposal: ActionProposal, ledger: ConcernLedger):
    """Rewrite payload leaves that match original ledger values under perturbation."""
    orig_values = {v.id: v.value for v in ledger.variables}

    def commit_fn(projected: ConcernLedger):
        def rewrite(obj):
            if isinstance(obj, dict):
                return {k: rewrite(v) for k, v in obj.items()}
            if isinstance(obj, list):
                return [rewrite(x) for x in obj]
            for _vid, oval in orig_values.items():
                pvar = projected.by_id(_vid)
                if pvar is not None and obj == oval:
                    return pvar.value
            return obj

        return rewrite(copy.deepcopy(proposal.payload))

    return commit_fn


def score_proposal(
    task: TaskSpec,
    env: Any,
    proposal: ActionProposal,
    *,
    gauge_budget: int = 0,
    gauge_min_concern: float = 0.5,
    thresholds: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Score one action through transport/proxy/reopen/validator gates."""
    state = env.reset(task)
    variables = ConcernMapper().extract(task, state)
    surfaces = SurfaceMapper().identify(task, variables)
    ledger = make_ledger(task, variables, surfaces)

    transport = TransportAuditor().check(proposal, ledger, state)
    if gauge_budget > 0:
        log = events_from_ledger(ledger)
        proxy = ProxyAdversary().check(
            proposal,
            ledger,
            state,
            env,
            log=log,
            commit_fn=tracking_commit_fn(proposal, ledger),
            gauge_budget=gauge_budget,
            gauge_min_concern=gauge_min_concern,
        )
    else:
        proxy = ProxyAdversary().check(proposal, ledger, state, env)
    reopen = ReopenabilityGovernor().check(proposal, ledger, state)
    validators = Verifier().validate(proposal, ledger, state, env)
    cert = make_certificate(
        task=task,
        ledger=ledger,
        proposal=proposal,
        transport=transport,
        proxy=proxy,
        reopen=reopen,
        validators=validators,
        thresholds=thresholds,
    )
    env_success = False
    if cert.decision == "allow":
        state = env.execute(proposal, state)
        s_fn = getattr(env, "success", None)
        env_success = bool(s_fn(state)) if callable(s_fn) else state.done

    gauge_failed = [r for r in cert.gauge_results if not r.passed]
    transport_failed = [r for r in transport if not r.passed]
    return {
        "decision": cert.decision,
        "load_score": cert.load_score,
        "final_success_if_allowed": env_success,
        "failed_gates": [
            r.gate_name
            for r in (transport + proxy + reopen + validators)
            if not r.passed
        ],
        "gauge_gate_count": len(cert.gauge_results),
        "gauge_failed_count": len(gauge_failed),
        "caught_by_transport": bool(transport_failed),
        "caught_by_gauge": bool(gauge_failed),
        "allowed": cert.decision == "allow",
        "blocked": cert.decision != "allow",
    }


def evaluate_heldout(
    *,
    suites: list[str],
    seeds: int,
    gauge_budget: int,
    gauge_min_concern: float = 0.5,
    thresholds: dict[str, float] | None = None,
) -> list[dict[str, Any]]:
    """Run held-out good/bad variants; return flat row list."""
    rows: list[dict[str, Any]] = []
    for suite_name in suites:
        suite = load_suite(suite_name)
        builder = VARIANT_BUILDERS.get(suite_name)
        if builder is None:
            continue
        for seed in range(seeds):
            task = suite.generate(seed)
            env = suite.make_env()
            ep = (task.metadata or {}).get("expected_payload", {}) or {}
            surface_id = ((task.metadata or {}).get("surfaces") or [{"id": "tool_call"}])[
                0
            ]["id"]
            action_type = (task.metadata or {}).get("expected_action_type", "answer")
            good = ActionProposal(
                action_id="good",
                surface_id=surface_id,
                action_type=action_type,
                payload=copy.deepcopy(ep),
                rationale="oracle payload",
                claimed_variables_used=(task.metadata or {}).get(
                    "critical_variable_ids", []
                ),
            )
            good_result = score_proposal(
                task,
                env,
                good,
                gauge_budget=gauge_budget,
                gauge_min_concern=gauge_min_concern,
                thresholds=thresholds,
            )
            rows.append(
                {"suite": suite_name, "seed": seed, "variant": "good", **good_result}
            )
            for label, bad in builder(good, task):
                bad_result = score_proposal(
                    task,
                    suite.make_env(),
                    bad,
                    gauge_budget=gauge_budget,
                    gauge_min_concern=gauge_min_concern,
                    thresholds=thresholds,
                )
                rows.append(
                    {
                        "suite": suite_name,
                        "seed": seed,
                        "variant": label,
                        **bad_result,
                    }
                )
    return rows


def aggregate_heldout(rows: list[dict[str, Any]]) -> dict[str, float]:
    """Summarize held-out catch and good-allow rates."""
    good = [r for r in rows if r["variant"] == "good"]
    held = [r for r in rows if r["variant"] != "good"]
    n_good = max(1, len(good))
    n_held = max(1, len(held))
    catch = sum(1 for r in held if r["blocked"]) / n_held
    gauge_catch = sum(1 for r in held if r.get("caught_by_gauge")) / n_held
    good_allow = sum(1 for r in good if r["allowed"]) / n_good
    mean_load = sum(float(r.get("load_score") or 0.0) for r in rows) / max(1, len(rows))
    return {
        "heldout_catch_rate": catch,
        "heldout_gauge_catch_rate": gauge_catch,
        "good_allow_rate": good_allow,
        "mean_load_score": mean_load,
        "n_good": float(len(good)),
        "n_heldout": float(len(held)),
    }
