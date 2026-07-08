"""Audit multi-agent orchestration traces as transport and gauge evidence."""

from __future__ import annotations

from typing import Any

from ..core.schemas import ActionProposal, ConcernLedger, GateResult, State


class OrchestrationAuditor:
    """Checks whether multi-agent handoffs preserve concern variables.

    External systems can include an orchestration trace in the proposal payload:

    ```json
    {
      "orchestration": {
        "handoffs": [
          {"to": "worker", "variables": ["target_file"], "access_list": ["plan"]}
        ],
        "shared_transcript": false
      }
    }
    ```

    LBAH does not require a trace for ordinary single-agent proposals. When a
    task sets `metadata.requires_orchestration_trace`, missing trace evidence is
    a failed transport gate.
    """

    def __init__(self, min_concern: float = 0.7):
        self.min_concern = min_concern

    def check(
        self,
        proposal: ActionProposal,
        ledger: ConcernLedger,
        state: State,
    ) -> list[GateResult]:
        del state
        trace = self._trace_from_payload(proposal.payload)
        required = bool((ledger.task.metadata or {}).get("requires_orchestration_trace"))
        if trace is None:
            if not required:
                return []
            return [
                GateResult(
                    gate_name="orchestration::trace_present",
                    gate_kind="transport",
                    passed=False,
                    score=0.0,
                    reason="task requires orchestration trace, but proposal omitted it",
                    evidence={"payload_keys": sorted(proposal.payload.keys())},
                    weight=0.8,
                )
            ]

        handoffs = self._handoffs(trace)
        results: list[GateResult] = [
            GateResult(
                gate_name="orchestration::trace_present",
                gate_kind="transport",
                passed=True,
                score=1.0,
                reason="proposal includes orchestration trace",
                evidence={"handoff_count": len(handoffs)},
                weight=0.2,
            )
        ]

        variable_mentions = self._variable_mentions(handoffs)
        for var in ledger.variables:
            if var.concern < self.min_concern:
                continue
            if var.required_surfaces and proposal.surface_id not in var.required_surfaces:
                continue
            aliases = {var.id, var.name}
            if var.value is not None:
                aliases.add(str(var.value))
            present = bool(aliases & variable_mentions)
            results.append(
                GateResult(
                    gate_name=f"orchestration::transport::{var.id}",
                    gate_kind="transport",
                    passed=present,
                    score=1.0 if present else 0.0,
                    reason=(
                        f"high-concern variable '{var.id}' appears in handoff trace"
                        if present
                        else f"high-concern variable '{var.id}' missing from handoff trace"
                    ),
                    evidence={
                        "aliases_checked": sorted(aliases),
                        "mentions": sorted(variable_mentions),
                    },
                    concern_id=var.id,
                    weight=var.concern,
                )
            )

        collapse_risk = self._collapse_risk(trace, handoffs)
        results.append(
            GateResult(
                gate_name="orchestration::gauge_collapse",
                gate_kind="proxy",
                passed=not collapse_risk,
                score=0.0 if collapse_risk else 1.0,
                reason=(
                    "shared transcript lacks access-list isolation"
                    if collapse_risk
                    else "handoff topology preserves isolation or explicit access"
                ),
                evidence={
                    "shared_transcript": bool(trace.get("shared_transcript")),
                    "handoff_count": len(handoffs),
                },
                weight=0.7,
            )
        )
        return results

    @staticmethod
    def _trace_from_payload(payload: dict[str, Any]) -> dict[str, Any] | None:
        trace = payload.get("orchestration")
        if isinstance(trace, dict):
            return trace
        handoffs = payload.get("handoffs")
        if isinstance(handoffs, list):
            return {"handoffs": handoffs}
        return None

    @staticmethod
    def _handoffs(trace: dict[str, Any]) -> list[dict[str, Any]]:
        raw = trace.get("handoffs") or trace.get("steps") or []
        return [h for h in raw if isinstance(h, dict)]

    @staticmethod
    def _variable_mentions(handoffs: list[dict[str, Any]]) -> set[str]:
        mentions: set[str] = set()
        fields = (
            "variables",
            "concerns",
            "claimed_variables_used",
            "context_keys",
            "access_list",
        )
        for handoff in handoffs:
            for field in fields:
                value = handoff.get(field)
                if isinstance(value, str):
                    mentions.add(value)
                elif isinstance(value, list):
                    mentions.update(str(x) for x in value)
        return mentions

    @staticmethod
    def _collapse_risk(trace: dict[str, Any], handoffs: list[dict[str, Any]]) -> bool:
        if len(handoffs) < 2:
            return False
        if not trace.get("shared_transcript"):
            return False
        for handoff in handoffs:
            if handoff.get("access_list") or handoff.get("isolated"):
                return False
        return True
