"""Typed action and task contracts for the coding harness."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


CodingActionType = Literal[
    "inspect",
    "search",
    "read_file",
    "edit_file",
    "run_command",
    "run_tests",
    "finish",
]


class CodingTask(BaseModel):
    """A real-repository coding task.

    ``repo_path`` can be provided by the CLI or embedded in task YAML. Test
    commands are intentionally explicit so benchmark adapters can give every
    harness the same verifier surface.
    """

    model_config = ConfigDict(extra="allow")

    task_id: str
    instruction: str
    repo_path: str | None = None
    test_commands: list[list[str] | str] = Field(default_factory=list)
    allowed_paths: list[str] = Field(default_factory=list)
    disallowed_paths: list[str] = Field(
        default_factory=lambda: [".git", ".pytest_cache", "__pycache__"]
    )
    success_criteria: list[str] = Field(default_factory=list)
    known_risks: list[str] = Field(default_factory=list)
    max_steps: int = 20
    metadata: dict[str, Any] = Field(default_factory=dict)


class CodingAction(BaseModel):
    """One inspect/edit/test/finish action proposed by a coding agent."""

    model_config = ConfigDict(extra="allow")

    action_id: str
    action_type: CodingActionType
    payload: dict[str, Any] = Field(default_factory=dict)
    rationale: str | None = None
    concerns_addressed: list[str] = Field(default_factory=list)
    ledger_updates: list[dict[str, Any]] = Field(default_factory=list)


class CodingObservation(BaseModel):
    """Observation returned to the agent after a coding action."""

    model_config = ConfigDict(extra="allow")

    action_id: str
    action_type: CodingActionType
    success: bool
    message: str
    data: dict[str, Any] = Field(default_factory=dict)
