"""Proxy adversary: can this proposal pass for the wrong reason?"""

from __future__ import annotations

import json
from typing import Any

from ..core.schemas import ActionProposal, ConcernLedger, ConcernVariable, GateResult, State


def _all_leaf_values(value: Any) -> list[Any]:
    out: list[Any] = []

    def walk(v: Any) -> None:
        if isinstance(v, dict):
            for x in v.values():
                walk(x)
        elif isinstance(v, (list, tuple)):
            for x in v:
                walk(x)
        else:
            out.append(v)

    walk(value)
    return out


class ProxyAdversary:
    """Runs a battery of proxy-shortcut checks.

    The default checks are deterministic and target the four proxy failure
    modes called out in the design doc:

      * `wrong_slot`: the proposal uses a distractor variable instead of the
        critical one.
      * `constant_answer`: the proposal is invariant across concern variables.
      * `stale_value`: the value used comes from a stale variable.
      * `forbidden_field_present`: any variable tagged as a forbidden inclusion
        appears in the payload.
    """

    def __init__(self):
        self.surfaced_variables: list[ConcernVariable] = []

    # ------------------------------------------------------------------

    def check(
        self,
        proposal: ActionProposal,
        ledger: ConcernLedger,
        state: State,
        env: Any = None,
    ) -> list[GateResult]:
        results: list[GateResult] = []
        payload_leaves = [str(x).lower() for x in _all_leaf_values(proposal.payload) if x is not None]
        payload_str = json.dumps(proposal.payload, default=str).lower()

        # Discover the "critical variable" if any is marked so.
        critical_ids: set[str] = set(
            (ledger.task.metadata or {}).get("critical_variable_ids", []) or []
        )

        # 1. Wrong slot: if metadata declares a critical variable, then any OTHER
        # candidate variable's value present in the payload while the critical
        # value is missing is a proxy hit.
        if critical_ids:
            crit_hit = False
            distractor_hit: list[str] = []
            crit_values = [
                str(v.value).lower()
                for v in ledger.variables
                if v.id in critical_ids and v.value is not None
            ]
            for cv in crit_values:
                if cv in payload_leaves or cv in payload_str:
                    crit_hit = True
                    break
            for v in ledger.variables:
                if v.id in critical_ids or v.value is None:
                    continue
                vs = str(v.value).lower()
                if (vs in payload_leaves or vs in payload_str) and vs not in crit_values:
                    distractor_hit.append(v.id)
            wrong_slot_pass = crit_hit and not distractor_hit
            results.append(
                GateResult(
                    gate_name="proxy::wrong_slot",
                    gate_kind="proxy",
                    passed=wrong_slot_pass,
                    score=1.0 if wrong_slot_pass else 0.0,
                    reason=(
                        "critical variable present, no distractor hit"
                        if wrong_slot_pass
                        else f"critical_hit={crit_hit}, distractor_hit={distractor_hit}"
                    ),
                    evidence={
                        "critical_ids": sorted(critical_ids),
                        "distractor_ids": distractor_hit,
                        "crit_values": crit_values,
                    },
                    weight=1.0,
                )
            )

        # 2. Forbidden fields: any variable with proxy_risks tag "forbidden" whose
        # value shows up in the payload is a failure.
        forbidden_hits: list[str] = []
        for v in ledger.variables:
            tags = [r.lower() for r in v.proxy_risks]
            if "forbidden" in tags and v.value is not None:
                vs = str(v.value).lower()
                if vs in payload_leaves or vs in payload_str:
                    forbidden_hits.append(v.id)
        results.append(
            GateResult(
                gate_name="proxy::forbidden_field_present",
                gate_kind="proxy",
                passed=not forbidden_hits,
                score=0.0 if forbidden_hits else 1.0,
                reason=(
                    f"forbidden values present: {forbidden_hits}"
                    if forbidden_hits
                    else "no forbidden values in payload"
                ),
                evidence={"forbidden_ids": forbidden_hits},
                weight=1.0,
            )
        )

        # 3. Stale value: proposal.claimed_variables_used lists a variable whose
        # freshness is low.
        stale_used = [
            var.id
            for var in ledger.variables
            if var.id in proposal.claimed_variables_used and var.freshness < 0.5
        ]
        results.append(
            GateResult(
                gate_name="proxy::stale_value",
                gate_kind="proxy",
                passed=not stale_used,
                score=0.0 if stale_used else 1.0,
                reason=(
                    f"stale variables used: {stale_used}"
                    if stale_used
                    else "no stale variables claimed"
                ),
                evidence={"stale_ids": stale_used},
                weight=0.8,
            )
        )

        # 4. Environment-supplied proxy checks. Environments that know their
        # own proxies (e.g. coding envs) expose `proxy_checks(proposal, ledger, state)`.
        env_checks = getattr(env, "proxy_checks", None) if env is not None else None
        if callable(env_checks):
            for gr in env_checks(proposal, ledger, state):
                gr.gate_kind = "proxy"
                results.append(gr)

        # 5. Constant-answer detection: identical payload across steps is a proxy.
        history = state.scratch.setdefault("_proxy_history", [])
        current = json.dumps(proposal.payload, sort_keys=True, default=str)
        if history and all(h == current for h in history[-3:]):
            results.append(
                GateResult(
                    gate_name="proxy::constant_answer",
                    gate_kind="proxy",
                    passed=False,
                    score=0.0,
                    reason="proposal is invariant across recent steps",
                    evidence={"history": history[-3:]},
                    weight=0.6,
                )
            )
        history.append(current)

        return results
