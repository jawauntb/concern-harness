"""Tests for concern-aware orchestration auditing."""

from lbah.core.schemas import (
    ActionProposal,
    CommitmentSurface,
    ConcernLedger,
    ConcernVariable,
    State,
    TaskSpec,
)
from lbah.modules.orchestration_auditor import OrchestrationAuditor


def _ledger(requires_trace: bool = False) -> ConcernLedger:
    task = TaskSpec(
        task_id="multi",
        task_type="tool_use",
        instruction="coordinate experts",
        metadata={"requires_orchestration_trace": requires_trace},
    )
    variable = ConcernVariable(
        id="target_file",
        name="target_file",
        value="lbah/core/runner.py",
        concern=0.95,
        source="task",
        required_surfaces=["tool_call"],
    )
    surface = CommitmentSurface(id="tool_call", name="tool call", type="tool_call")
    return ConcernLedger(task=task, variables=[variable], surfaces=[surface])


def test_missing_required_trace_fails_transport():
    proposal = ActionProposal(
        action_id="a",
        surface_id="tool_call",
        action_type="answer",
        payload={"value": "lbah/core/runner.py"},
    )
    results = OrchestrationAuditor().check(
        proposal,
        _ledger(requires_trace=True),
        State(task_id="multi"),
    )
    assert results[0].gate_name == "orchestration::trace_present"
    assert not results[0].passed


def test_handoff_trace_must_carry_high_concern_variable():
    proposal = ActionProposal(
        action_id="a",
        surface_id="tool_call",
        action_type="answer",
        payload={
            "value": "lbah/core/runner.py",
            "orchestration": {
                "handoffs": [{"to": "worker", "variables": ["other"]}],
                "shared_transcript": False,
            },
        },
    )
    results = OrchestrationAuditor().check(proposal, _ledger(), State(task_id="multi"))
    transport = [r for r in results if r.gate_name == "orchestration::transport::target_file"]
    assert transport
    assert not transport[0].passed


def test_access_list_isolation_avoids_gauge_collapse():
    proposal = ActionProposal(
        action_id="a",
        surface_id="tool_call",
        action_type="answer",
        payload={
            "value": "lbah/core/runner.py",
            "orchestration": {
                "handoffs": [
                    {"to": "planner", "variables": ["target_file"], "access_list": []},
                    {"to": "worker", "variables": ["target_file"], "access_list": ["planner"]},
                ],
                "shared_transcript": True,
            },
        },
    )
    results = OrchestrationAuditor().check(proposal, _ledger(), State(task_id="multi"))
    collapse = [r for r in results if r.gate_name == "orchestration::gauge_collapse"][0]
    assert collapse.passed
