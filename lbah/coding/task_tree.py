"""Typed task-tree contracts for bounded recursive coding harnesses."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .actions import CodingAction, CodingTask


ChildRole = Literal[
    "repo_navigator",
    "failure_inspector",
    "patch_proposer",
    "adversarial_reviewer",
    "test_planner",
    "custom",
]
ChildTaskStatus = Literal["pending", "running", "passed", "failed", "skipped"]


class ChildTaskSpec(BaseModel):
    """One bounded child role the parent harness can validate and reduce."""

    model_config = ConfigDict(extra="allow")

    child_id: str
    role: ChildRole
    goal: str
    concerns: list[str] = Field(default_factory=list)
    allowed_paths: list[str] = Field(default_factory=list)
    budget_steps: int = Field(default=4, ge=1)
    evidence_required: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ChildTaskResult(BaseModel):
    """Validated output from a child role."""

    model_config = ConfigDict(extra="allow")

    child_id: str
    role: ChildRole
    status: ChildTaskStatus
    summary: str
    evidence: list[str] = Field(default_factory=list)
    proposed_actions: list[CodingAction] = Field(default_factory=list)
    ledger_updates: list[dict[str, Any]] = Field(default_factory=list)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)


class TaskTreeNode(BaseModel):
    """A serializable task-tree node for run artifacts and future nesting."""

    spec: ChildTaskSpec
    result: ChildTaskResult | None = None
    children: list[TaskTreeNode] = Field(default_factory=list)


def default_child_tasks(task: CodingTask) -> list[ChildTaskSpec]:
    """Build child tasks from task metadata, or return the default role set."""

    configured = task.metadata.get("recursive_children")
    if configured is not None:
        return [
            _coerce_configured_child(task, item, index)
            for index, item in enumerate(configured)
        ]

    allowed_paths = list(task.allowed_paths)
    return [
        ChildTaskSpec(
            child_id="repo_navigator",
            role="repo_navigator",
            goal="Identify the files, contracts, and existing tests relevant to the task.",
            concerns=["task"],
            allowed_paths=allowed_paths,
            evidence_required=["relevant files"],
        ),
        ChildTaskSpec(
            child_id="test_planner",
            role="test_planner",
            goal="Identify the verification command and the smallest tests that prove the task.",
            concerns=["task"],
            allowed_paths=allowed_paths,
            evidence_required=["test strategy"],
        ),
        ChildTaskSpec(
            child_id="patch_proposer",
            role="patch_proposer",
            goal="Propose a focused patch plan with concern links and no test weakening.",
            concerns=["task"],
            allowed_paths=allowed_paths,
            evidence_required=["patch plan"],
        ),
        ChildTaskSpec(
            child_id="adversarial_reviewer",
            role="adversarial_reviewer",
            goal="Look for ways the patch could pass tests while violating the task.",
            concerns=["task", "risk_0"],
            allowed_paths=allowed_paths,
            evidence_required=["risk review"],
        ),
    ]


def _coerce_configured_child(task: CodingTask, raw: Any, index: int) -> ChildTaskSpec:
    if not isinstance(raw, dict):
        raise TypeError("recursive_children entries must be objects")
    data = dict(raw)
    role = data.setdefault("role", "custom")
    data.setdefault("child_id", f"{role}_{index}")
    data.setdefault("goal", task.instruction)
    data.setdefault("allowed_paths", list(task.allowed_paths))
    return ChildTaskSpec.model_validate(data)
