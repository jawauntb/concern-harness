"""Transport auditor: did the high-concern variables reach the action?"""

from __future__ import annotations

import json
from typing import Any

from ..core.schemas import ActionProposal, ConcernLedger, GateResult, State


def _flatten(value: Any) -> list[Any]:
    """Flatten nested structures into a list of primitive leaves."""
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


def _string_of(payload: Any) -> str:
    try:
        return json.dumps(payload, default=str)
    except Exception:
        return str(payload)


def _canonical(value: object) -> str:
    """Canonicalize a leaf value for equality comparison.

    No normalization — case and whitespace matter. Any relaxation should live
    on the ConcernVariable's `match_mode` field, not here.
    """
    return str(value)


class TransportAuditor:
    """Deterministic transport check: variable value must appear in proposal payload.

    Uses two-tier matching:
    - if the concern variable has a concrete `value`, require an EXACT
      canonicalized leaf equality anywhere in the payload;
    - otherwise fall back to substring containment.

    An LLM-backed subclass could replace this with a semantic check.
    """

    def __init__(self, min_concern: float = 0.0, strict_leaf_equality: bool = True):
        self.min_concern = min_concern
        self.strict_leaf_equality = strict_leaf_equality

    def check(
        self,
        proposal: ActionProposal,
        ledger: ConcernLedger,
        state: State,
    ) -> list[GateResult]:
        results: list[GateResult] = []
        payload_str = _string_of(proposal.payload).lower()
        payload_leaves_raw = [x for x in _flatten(proposal.payload) if x is not None]
        payload_leaves = [str(x).lower() for x in payload_leaves_raw]
        payload_leaves_canonical = [_canonical(x) for x in payload_leaves_raw]

        for var in ledger.variables:
            if var.concern < self.min_concern:
                continue
            # Only audit variables whose required_surfaces list includes this surface.
            if var.required_surfaces and proposal.surface_id not in var.required_surfaces:
                continue
            # Forbidden-tagged variables must NOT appear in the payload — the
            # proxy adversary handles that. Skip them here.
            if "forbidden" in [r.lower() for r in var.proxy_risks]:
                continue

            expected = var.value
            if expected is None:
                # Nothing concrete to search for — skip transport, but note.
                results.append(
                    GateResult(
                        gate_name=f"transport::{var.id}",
                        gate_kind="transport",
                        passed=True,
                        score=1.0,
                        reason="variable has no concrete value; transport unchecked",
                        concern_id=var.id,
                        weight=var.concern,
                    )
                )
                continue

            expected_str = str(expected).lower()
            expected_canonical = _canonical(expected)
            expected_raw = str(expected)

            leaf_hit = expected_str in payload_leaves
            canonical_leaf_hit = expected_canonical in payload_leaves_canonical
            substr_hit = expected_str in payload_str
            raw_leaf_hit = any(expected_raw == str(x) for x in payload_leaves_raw)
            raw_substr_hit = expected_raw in _string_of(proposal.payload)

            mode = getattr(var, "match_mode", "exact_leaf")
            if mode == "substring":
                passed = raw_substr_hit or substr_hit
            elif mode == "exact_leaf" or (mode == "semantic" and self.strict_leaf_equality):
                # Exact leaf equality (case + whitespace sensitive). This is
                # the strong default the paper's transport obligation asks
                # for: the concern variable's value must survive as an
                # identifiable leaf in the commitment surface.
                passed = raw_leaf_hit
            else:
                passed = leaf_hit or substr_hit

            results.append(
                GateResult(
                    gate_name=f"transport::{var.id}",
                    gate_kind="transport",
                    passed=passed,
                    score=1.0 if passed else 0.0,
                    reason=(
                        f"variable '{var.id}' present in payload"
                        if passed
                        else f"variable '{var.id}' expected canonical value '{expected_canonical}' not an exact leaf in payload"
                    ),
                    evidence={
                        "expected": expected,
                        "expected_canonical": expected_canonical,
                        "canonical_leaf_hit": canonical_leaf_hit,
                        "leaf_hit": leaf_hit,
                        "substr_hit": substr_hit,
                        "payload": proposal.payload,
                    },
                    concern_id=var.id,
                    weight=var.concern,
                )
            )
        return results
