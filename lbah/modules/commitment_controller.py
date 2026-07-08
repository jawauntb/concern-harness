"""Commitment controller: wraps decide_from_gates for pluggable policies."""

from __future__ import annotations

from ..core.certificates import decide_from_gates
from ..core.schemas import (
    ActionProposal,
    ConcernLedger,
    GateResult,
    LoadBearingCertificate,
    TaskSpec,
)


class CommitmentController:
    """Thin wrapper allowing subclasses to override decision policy.

    The default runner calls `certificates.make_certificate` directly; users
    who want an LLM-backed judge can instantiate a subclass and pass it through
    `HarnessModules.commitment_controller`.
    """

    def __init__(self, thresholds: dict[str, float] | None = None):
        self.thresholds = thresholds or {}

    def decide(
        self,
        task: TaskSpec,
        ledger: ConcernLedger,
        proposal: ActionProposal,
        transport: list[GateResult],
        proxy: list[GateResult],
        reopen: list[GateResult],
        validators: list[GateResult],
    ) -> str:
        return decide_from_gates(
            task,
            ledger,
            proposal,
            transport,
            proxy,
            reopen,
            validators,
            thresholds=self.thresholds,
        )
