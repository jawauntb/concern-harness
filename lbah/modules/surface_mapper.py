"""Identify the commitment surfaces relevant to a task."""

from __future__ import annotations

from ..core.schemas import CommitmentSurface, ConcernVariable, TaskSpec


DEFAULT_SURFACE_BY_TASK_TYPE: dict[str, tuple[str, str, bool]] = {
    "coding": ("code_diff", "git diff", False),
    "tool_use": ("tool_call", "tool invocation", False),
    "research": ("final_answer", "final answer with citations", False),
    "browser": ("browser_action", "browser action", False),
    "memory": ("memory_write", "memory write", False),
    "multi_step": ("final_answer", "final answer", False),
    "custom": ("final_answer", "final answer", False),
}


DEFAULT_VALIDATORS_BY_TYPE: dict[str, list[str]] = {
    "code_diff": [
        "unit_tests_pass",
        "no_test_weakening",
        "no_fixture_hardcode",
        "public_api_unchanged",
        "minimal_diff",
    ],
    "tool_call": [
        "schema_valid",
        "required_fields_present",
        "forbidden_fields_absent",
        "irreversible_confirmed",
    ],
    "final_answer": [
        "answer_present",
        "no_unsupported_claims",
    ],
    "browser_action": [
        "url_matches_intent",
        "no_dialog_triggered",
    ],
    "memory_write": [
        "write_key_expected",
        "no_conflict_with_stale_value",
    ],
    "shell_command": [
        "no_forbidden_flags",
        "env_target_matches",
    ],
    "json_field": ["field_present", "field_type_valid"],
    "email": ["recipient_matches", "no_forbidden_recipient"],
    "refusal": ["refusal_justified"],
    "custom": [],
}


class SurfaceMapper:
    def identify(
        self,
        task: TaskSpec,
        variables: list[ConcernVariable],
    ) -> list[CommitmentSurface]:
        # Explicit metadata wins.
        meta_surfaces = (task.metadata or {}).get("surfaces")
        if meta_surfaces:
            return [CommitmentSurface.model_validate(s) for s in meta_surfaces]

        surface_type, name, irreversible = DEFAULT_SURFACE_BY_TASK_TYPE.get(
            task.task_type, ("final_answer", "final answer", False)
        )

        required_surface_ids: set[str] = set()
        for v in variables:
            for s in v.required_surfaces:
                required_surface_ids.add(s)
        if not required_surface_ids:
            required_surface_ids.add(surface_type)

        surfaces: list[CommitmentSurface] = []
        for sid in sorted(required_surface_ids):
            surfaces.append(
                CommitmentSurface(
                    id=sid,
                    name=sid.replace("_", " "),
                    type=sid if sid in DEFAULT_VALIDATORS_BY_TYPE else "custom",  # type: ignore[arg-type]
                    irreversible=task.irreversible or irreversible,
                    validators=DEFAULT_VALIDATORS_BY_TYPE.get(sid, []),
                )
            )
        return surfaces
