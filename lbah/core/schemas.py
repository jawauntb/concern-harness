"""Pydantic schemas for the load-bearing agent harness.

These schemas are the wire format between every module and adapter. Adapters
that live outside the Python process (HTTP, CLI) round-trip through the JSON
representation of these types.
"""

from __future__ import annotations

from typing import Any, Literal
from pydantic import BaseModel, Field, ConfigDict


SurfaceType = Literal[
    "final_answer",
    "tool_call",
    "shell_command",
    "code_diff",
    "json_field",
    "browser_action",
    "memory_write",
    "email",
    "refusal",
    "custom",
]


TaskType = Literal[
    "coding",
    "tool_use",
    "research",
    "browser",
    "memory",
    "multi_step",
    "custom",
]


Decision = Literal["allow", "block", "reopen", "ask_user", "revise"]


class TaskSpec(BaseModel):
    """A single task the harness is asked to run."""

    model_config = ConfigDict(extra="allow")

    task_id: str
    task_type: TaskType
    instruction: str
    environment: dict[str, Any] = Field(default_factory=dict)
    allowed_tools: list[str] = Field(default_factory=list)
    success_criteria: list[str] = Field(default_factory=list)
    known_proxy_risks: list[str] = Field(default_factory=list)
    irreversible: bool = False
    max_steps: int = 20
    metadata: dict[str, Any] = Field(default_factory=dict)


class ConcernVariable(BaseModel):
    """A distinction that must survive from task -> commitment surface."""

    id: str
    name: str
    value: Any | None = None
    concern: float = Field(ge=0.0, le=1.0)
    source: str
    freshness: float = Field(default=1.0, ge=0.0, le=1.0)
    required_surfaces: list[str] = Field(default_factory=list)
    proxy_risks: list[str] = Field(default_factory=list)
    reopen_conditions: list[str] = Field(default_factory=list)
    # How the transport auditor should match this variable's value in a
    # commitment surface payload:
    #   "exact_leaf" — variable value must appear as an exact string leaf
    #                  anywhere in the payload (case + whitespace sensitive).
    #                  Default. Catches case, whitespace, fullname, and
    #                  reformatting proxies.
    #   "substring"  — variable value can appear as a substring inside a
    #                  larger leaf (useful for thematic markers embedded in
    #                  free-form text answers).
    #   "semantic"   — reserved for LLM-backed transport auditors.
    match_mode: Literal["exact_leaf", "substring", "semantic"] = "exact_leaf"


class CommitmentSurface(BaseModel):
    """A place where internal state becomes externally consequential."""

    id: str
    name: str
    type: SurfaceType
    irreversible: bool = False
    validators: list[str] = Field(default_factory=list)


class ActionProposal(BaseModel):
    """What an agent proposes to do."""

    model_config = ConfigDict(extra="allow")

    action_id: str
    surface_id: str
    action_type: str
    payload: dict[str, Any] = Field(default_factory=dict)
    rationale: str | None = None
    claimed_variables_used: list[str] = Field(default_factory=list)


class GateResult(BaseModel):
    """Outcome of a single gate check (transport, proxy, reopen, validator)."""

    gate_name: str
    gate_kind: Literal["transport", "proxy", "reopen", "validator"] = "validator"
    passed: bool
    score: float = Field(ge=0.0, le=1.0)
    reason: str
    evidence: dict[str, Any] = Field(default_factory=dict)
    concern_id: str | None = None
    weight: float = 1.0


class LoadBearingCertificate(BaseModel):
    """The main output of a step: was the intended structure load-bearing?"""

    task_id: str
    action_id: str
    surface_id: str
    behavior_passed: bool
    transport_results: list[GateResult] = Field(default_factory=list)
    proxy_results: list[GateResult] = Field(default_factory=list)
    # First-class gauge-fixing verdicts (also present in proxy_results for
    # backward compatibility). Populated when gauge_probe_budget > 0.
    gauge_results: list[GateResult] = Field(default_factory=list)
    reopenability_results: list[GateResult] = Field(default_factory=list)
    validator_results: list[GateResult] = Field(default_factory=list)
    load_score: float
    behavior_score: float = 1.0
    transport_score: float = 1.0
    proxy_resistance_score: float = 1.0
    reopenability_score: float = 1.0
    commitment_validity_score: float = 1.0
    decision: Decision
    summary: str = ""


class Observation(BaseModel):
    model_config = ConfigDict(extra="allow")

    text: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)


class State(BaseModel):
    """Environment state, shared with the agent between steps."""

    model_config = ConfigDict(extra="allow")

    task_id: str
    step: int = 0
    done: bool = False
    last_observation: Observation | None = None
    scratch: dict[str, Any] = Field(default_factory=dict)


class ConcernLedger(BaseModel):
    """The living contract of what must survive for this task."""

    task: TaskSpec
    variables: list[ConcernVariable] = Field(default_factory=list)
    surfaces: list[CommitmentSurface] = Field(default_factory=list)
    updates: list[dict[str, Any]] = Field(default_factory=list)

    def by_id(self, var_id: str) -> ConcernVariable | None:
        for v in self.variables:
            if v.id == var_id:
                return v
        return None

    def surface_by_id(self, sid: str) -> CommitmentSurface | None:
        for s in self.surfaces:
            if s.id == sid:
                return s
        return None


class RunResult(BaseModel):
    task_id: str
    agent: str
    mode: str
    final_success: bool
    final_state: dict[str, Any]
    certificates: list[LoadBearingCertificate] = Field(default_factory=list)
    load_score: float = 0.0
    behavior_score: float = 0.0
    transport_score: float = 0.0
    proxy_resistance_score: float = 0.0
    reopenability_score: float = 0.0
    commitment_validity_score: float = 0.0
    tokens: int = 0
    wall_time_seconds: float = 0.0
    cost_estimate: float = 0.0
    failed_gates: list[str] = Field(default_factory=list)
    notes: str = ""
    # Serialized ConcernEventLog (model_dump). Stored as a dict to keep schemas
    # free of a dependency on core.events; reconstruct with
    # ConcernEventLog.model_validate(run.event_log) to query lineage/diff.
    event_log: dict[str, Any] | None = None
