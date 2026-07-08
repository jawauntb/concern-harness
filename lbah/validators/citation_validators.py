"""Validators for retrieval/citation commitment surfaces."""

from __future__ import annotations

from typing import Any

from ..core.schemas import ActionProposal, ConcernLedger, GateResult, State


def answer_present(
    proposal: ActionProposal, ledger: ConcernLedger, state: State, env: Any
) -> GateResult:
    answer = proposal.payload.get("answer") or proposal.payload.get("value")
    ok = bool(answer)
    return GateResult(
        gate_name="validator::answer_present",
        passed=ok,
        score=1.0 if ok else 0.0,
        reason="answer present" if ok else "no answer field in payload",
    )


def no_unsupported_claims(
    proposal: ActionProposal, ledger: ConcernLedger, state: State, env: Any
) -> GateResult:
    claims = proposal.payload.get("claims") or []
    citations = proposal.payload.get("citations") or []
    if not claims:
        return GateResult(
            gate_name="validator::no_unsupported_claims",
            passed=True,
            score=1.0,
            reason="no explicit claims recorded",
            weight=0.3,
        )
    supported = 0
    unsupported: list[dict] = []
    docs = (ledger.task.metadata or {}).get("documents", {}) or {}
    for claim in claims:
        cite_id = claim.get("citation") if isinstance(claim, dict) else None
        if cite_id and cite_id in docs:
            doc_text = str(docs[cite_id]).lower()
            claim_text = str(claim.get("text", "")).lower() if isinstance(claim, dict) else str(claim).lower()
            tokens = [t for t in claim_text.split() if len(t) > 3]
            hit = sum(1 for t in tokens if t in doc_text)
            if tokens and hit / len(tokens) >= 0.5:
                supported += 1
            else:
                unsupported.append({"claim": claim_text, "citation": cite_id, "hit_ratio": hit / max(1, len(tokens))})
        else:
            unsupported.append({"claim": claim, "citation": cite_id, "reason": "no source"})
    passed = not unsupported
    return GateResult(
        gate_name="validator::no_unsupported_claims",
        passed=passed,
        score=supported / max(1, len(claims)),
        reason="all claims supported" if passed else f"{len(unsupported)} unsupported claims",
        evidence={"unsupported": unsupported},
    )


def citations_match_claims(
    proposal: ActionProposal, ledger: ConcernLedger, state: State, env: Any
) -> GateResult:
    claims = proposal.payload.get("claims") or []
    if not claims:
        return GateResult(
            gate_name="validator::citations_match_claims",
            passed=True,
            score=1.0,
            reason="no claims to check",
            weight=0.3,
        )
    missing = [i for i, c in enumerate(claims) if isinstance(c, dict) and not c.get("citation")]
    passed = not missing
    return GateResult(
        gate_name="validator::citations_match_claims",
        passed=passed,
        score=1.0 - len(missing) / len(claims),
        reason=("every claim cited" if passed else f"{len(missing)} claims lack citations"),
        evidence={"missing_indices": missing},
    )
