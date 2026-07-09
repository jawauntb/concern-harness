"""Verifier: run deterministic validators for the proposal's commitment surface."""

from __future__ import annotations

from typing import Any, Callable, cast

from ..core.schemas import ActionProposal, ConcernLedger, GateResult, State
from ..validators import (
    code_validators,
    tool_validators,
    citation_validators,
    json_validators,
    safety_validators,
)


ValidatorFn = Callable[[ActionProposal, ConcernLedger, State, Any], GateResult]


REGISTRY: dict[str, ValidatorFn] = {
    # code
    "unit_tests_pass": code_validators.unit_tests_pass,
    "no_test_weakening": code_validators.no_test_weakening,
    "no_fixture_hardcode": code_validators.no_fixture_hardcode,
    "public_api_unchanged": code_validators.public_api_unchanged,
    "minimal_diff": code_validators.minimal_diff,
    "no_error_silencing": code_validators.no_error_silencing,
    # tool
    "schema_valid": tool_validators.schema_valid,
    "required_fields_present": tool_validators.required_fields_present,
    "forbidden_fields_absent": tool_validators.forbidden_fields_absent,
    "irreversible_confirmed": tool_validators.irreversible_confirmed,
    "result_ignore": tool_validators.result_ignore,
    "output_fabrication": tool_validators.output_fabrication,
    "tool_skip": tool_validators.tool_skip,
    "unnecessary_tool_use": tool_validators.unnecessary_tool_use,
    # citation
    "answer_present": citation_validators.answer_present,
    "no_unsupported_claims": citation_validators.no_unsupported_claims,
    "citations_match_claims": citation_validators.citations_match_claims,
    # json
    "field_present": json_validators.field_present,
    "field_type_valid": json_validators.field_type_valid,
    # safety
    "no_forbidden_flags": safety_validators.no_forbidden_flags,
    "env_target_matches": safety_validators.env_target_matches,
    "url_matches_intent": safety_validators.url_matches_intent,
    "no_dialog_triggered": safety_validators.no_dialog_triggered,
    "write_key_expected": safety_validators.write_key_expected,
    "no_conflict_with_stale_value": safety_validators.no_conflict_with_stale_value,
    "recipient_matches": safety_validators.recipient_matches,
    "no_forbidden_recipient": safety_validators.no_forbidden_recipient,
    "refusal_justified": safety_validators.refusal_justified,
}


class Verifier:
    def __init__(self, extra: dict[str, ValidatorFn] | None = None):
        self.registry = dict(REGISTRY)
        if extra:
            self.registry.update(extra)

    def validate(
        self,
        proposal: ActionProposal,
        ledger: ConcernLedger,
        state: State,
        env: Any,
    ) -> list[GateResult]:
        surface = ledger.surface_by_id(proposal.surface_id)
        results: list[GateResult] = []
        if surface is None:
            results.append(
                GateResult(
                    gate_name="validator::unknown_surface",
                    gate_kind="validator",
                    passed=False,
                    score=0.0,
                    reason=f"proposal targets unknown surface {proposal.surface_id}",
                )
            )
            return results
        for validator_name in surface.validators:
            fn = self.registry.get(validator_name)
            if fn is None:
                # Unknown validators are treated as skipped but noted.
                results.append(
                    GateResult(
                        gate_name=f"validator::{validator_name}",
                        gate_kind="validator",
                        passed=True,
                        score=1.0,
                        reason="no implementation registered for validator; skipped",
                        weight=0.1,
                    )
                )
                continue
            try:
                gr = fn(proposal, ledger, state, env)
                gr.gate_kind = "validator"
                gr.gate_name = gr.gate_name or f"validator::{validator_name}"
                results.append(gr)
            except Exception as exc:
                results.append(
                    GateResult(
                        gate_name=f"validator::{validator_name}",
                        gate_kind="validator",
                        passed=False,
                        score=0.0,
                        reason=f"validator raised {type(exc).__name__}: {exc}",
                    )
                )
        # If the environment supplies extra validators (e.g., hidden tests), append them.
        extra = getattr(env, "extra_validators", None)
        if callable(extra):
            for gr in cast(list[GateResult], extra(proposal, ledger, state)):
                gr.gate_kind = "validator"
                results.append(gr)
        return results
