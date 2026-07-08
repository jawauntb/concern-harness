"""Reopenability governor: should the agent recheck before acting?"""

from __future__ import annotations

from typing import Any

from ..core.schemas import (
    ActionProposal,
    ConcernLedger,
    ConcernVariable,
    GateResult,
    LoadBearingCertificate,
    State,
)


class ReopenabilityGovernor:
    """Compute reopen score per high-concern variable and decide whether to
    force a check before commitment.

    ReopenScore = concern * (1 - freshness) * irreversibility * cheapness * proxy_risk
    """

    def __init__(
        self,
        threshold_low_risk: float = 0.65,
        threshold_normal: float = 0.45,
        threshold_high_risk: float = 0.25,
        threshold_irreversible: float = 0.15,
    ):
        self.threshold_low_risk = threshold_low_risk
        self.threshold_normal = threshold_normal
        self.threshold_high_risk = threshold_high_risk
        self.threshold_irreversible = threshold_irreversible

    # ------------------------------------------------------------------

    def _threshold(self, ledger: ConcernLedger, proposal: ActionProposal) -> float:
        surface = ledger.surface_by_id(proposal.surface_id)
        if ledger.task.irreversible or (surface and surface.irreversible):
            return self.threshold_irreversible
        if any(v.concern >= 0.9 for v in ledger.variables):
            return self.threshold_high_risk
        return self.threshold_normal

    def _reopen_score(self, var: ConcernVariable, irreversible: bool) -> float:
        cheapness = 1.0  # assume cheap; environments can supply better estimate
        proxy_risk = min(1.0, 0.3 + 0.2 * len(var.proxy_risks))
        irreversibility = 1.0 if irreversible else 0.5
        return var.concern * (1.0 - var.freshness) * irreversibility * cheapness * proxy_risk

    # ------------------------------------------------------------------

    def check(
        self,
        proposal: ActionProposal,
        ledger: ConcernLedger,
        state: State,
    ) -> list[GateResult]:
        threshold = self._threshold(ledger, proposal)
        surface = ledger.surface_by_id(proposal.surface_id)
        irreversible = ledger.task.irreversible or (surface.irreversible if surface else False)

        results: list[GateResult] = []
        for var in ledger.variables:
            score = self._reopen_score(var, irreversible)
            needs_reopen = score >= threshold and var.freshness < 1.0
            if score == 0.0 and var.freshness == 1.0:
                continue  # fresh + no reopen pressure; no gate emitted
            results.append(
                GateResult(
                    gate_name=f"reopen::{var.id}",
                    gate_kind="reopen",
                    passed=not needs_reopen,
                    score=0.0 if needs_reopen else 1.0,
                    reason=(
                        f"variable '{var.id}' stale (freshness={var.freshness:.2f}, reopen_score={score:.2f})"
                        if needs_reopen
                        else f"variable '{var.id}' fresh enough (reopen_score={score:.2f})"
                    ),
                    evidence={
                        "freshness": var.freshness,
                        "reopen_score": score,
                        "threshold": threshold,
                    },
                    concern_id=var.id,
                    weight=var.concern if needs_reopen else var.concern * 0.5,
                )
            )
        return results

    # ------------------------------------------------------------------

    def reopen_action(
        self,
        certificate: LoadBearingCertificate,
        ledger: ConcernLedger,
    ) -> ActionProposal | None:
        stale = [r.concern_id for r in certificate.reopenability_results if not r.passed and r.concern_id]
        if not stale:
            return None
        return ActionProposal(
            action_id=f"reopen_{certificate.action_id}",
            surface_id="reopen",
            action_type="reopen",
            payload={"variables_to_refresh": stale},
            rationale="reopenability governor forced a refresh",
            claimed_variables_used=stale,
        )
