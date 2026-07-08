"""Concern-led working memory for coding tasks."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from .actions import CodingAction, CodingObservation, CodingTask


ConcernKind = Literal["fact", "hypothesis", "risk", "file", "test", "question", "evidence"]
ConcernStatus = Literal["open", "addressed", "rejected", "deferred"]


class CodingConcern(BaseModel):
    """A live concern used to steer and verify coding work."""

    id: str
    kind: ConcernKind
    text: str
    concern: float = Field(default=0.7, ge=0.0, le=1.0)
    status: ConcernStatus = "open"
    evidence: list[str] = Field(default_factory=list)


class CodingLedger(BaseModel):
    """Task-local state that makes verification failures actionable."""

    task_id: str
    instruction: str
    concerns: list[CodingConcern] = Field(default_factory=list)
    events: list[dict[str, Any]] = Field(default_factory=list)

    @classmethod
    def from_task(cls, task: CodingTask) -> "CodingLedger":
        concerns: list[CodingConcern] = [
            CodingConcern(
                id="task",
                kind="hypothesis",
                text=task.instruction,
                concern=0.9,
            )
        ]
        for i, criterion in enumerate(task.success_criteria):
            concerns.append(
                CodingConcern(
                    id=f"success_{i}",
                    kind="evidence",
                    text=criterion,
                    concern=0.85,
                )
            )
        for i, risk in enumerate(task.known_risks):
            concerns.append(
                CodingConcern(
                    id=f"risk_{i}",
                    kind="risk",
                    text=risk,
                    concern=0.8,
                )
            )
        for raw in task.metadata.get("coding_concerns", []) or []:
            concerns.append(CodingConcern.model_validate(raw))
        return cls(task_id=task.task_id, instruction=task.instruction, concerns=concerns)

    def by_id(self, concern_id: str) -> CodingConcern | None:
        for concern in self.concerns:
            if concern.id == concern_id:
                return concern
        return None

    def append_concern(self, concern: CodingConcern) -> None:
        existing = self.by_id(concern.id)
        if existing is None:
            self.concerns.append(concern)
            return
        if concern.concern >= existing.concern:
            existing.kind = concern.kind
            existing.text = concern.text
            existing.concern = concern.concern
            existing.status = concern.status
            existing.evidence = list(dict.fromkeys(existing.evidence + concern.evidence))

    def apply_action(self, action: CodingAction) -> None:
        for update in action.ledger_updates:
            self.append_concern(CodingConcern.model_validate(update))
        for concern_id in action.concerns_addressed:
            concern = self.by_id(concern_id)
            if concern is not None:
                concern.status = "addressed"
                if action.rationale:
                    concern.evidence.append(action.rationale)

    def apply_observation(self, observation: CodingObservation) -> None:
        self.events.append(observation.model_dump())
        if observation.action_type == "run_tests":
            concern_id = f"test_{len([c for c in self.concerns if c.kind == 'test'])}"
            status: ConcernStatus = "addressed" if observation.success else "open"
            self.append_concern(
                CodingConcern(
                    id=concern_id,
                    kind="test",
                    text=observation.message,
                    concern=0.9,
                    status=status,
                    evidence=[observation.message],
                )
            )
            if observation.success:
                for concern in self.concerns:
                    if concern.kind == "evidence" and concern.status == "open":
                        concern.status = "addressed"
                        concern.evidence.append(observation.message)
        if observation.success and observation.action_type in {"run_tests", "finish"}:
            for concern in self.concerns:
                if concern.id.startswith("verification_failure_") and concern.status == "open":
                    concern.status = "addressed"
                    concern.evidence.append(observation.message)
        if observation.action_type == "finish" and not observation.success:
            concern_id = f"verification_failure_{len(self.events)}"
            self.append_concern(
                CodingConcern(
                    id=concern_id,
                    kind="risk",
                    text=observation.message,
                    concern=0.95,
                    evidence=[observation.message],
                )
            )

    def unresolved(self, threshold: float = 0.7) -> list[CodingConcern]:
        return [
            concern
            for concern in self.concerns
            if concern.status == "open" and concern.concern >= threshold
        ]

    def to_agent_state(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "instruction": self.instruction,
            "concerns": [concern.model_dump() for concern in self.concerns],
            "unresolved": [concern.model_dump() for concern in self.unresolved()],
            "recent_events": self.events[-5:],
        }
