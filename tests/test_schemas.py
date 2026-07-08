"""Tests for the pydantic schemas."""

from lbah.core.schemas import (
    ActionProposal,
    CommitmentSurface,
    ConcernLedger,
    ConcernVariable,
    GateResult,
    LoadBearingCertificate,
    TaskSpec,
)


def test_task_spec_roundtrip():
    t = TaskSpec(
        task_id="t1",
        task_type="tool_use",
        instruction="do the thing",
        max_steps=5,
    )
    data = t.model_dump()
    assert TaskSpec.model_validate(data) == t


def test_concern_variable_bounds():
    v = ConcernVariable(
        id="v1", name="v", value="x", concern=0.7, source="task",
        required_surfaces=["tool_call"],
    )
    assert 0.0 <= v.concern <= 1.0


def test_ledger_lookup():
    task = TaskSpec(task_id="t", task_type="tool_use", instruction="")
    v = ConcernVariable(id="v", name="v", concern=1.0, source="s", required_surfaces=[])
    s = CommitmentSurface(id="tool_call", name="tool call", type="tool_call")
    ledger = ConcernLedger(task=task, variables=[v], surfaces=[s])
    assert ledger.by_id("v") is v
    assert ledger.surface_by_id("tool_call") is s
    assert ledger.by_id("nope") is None


def test_certificate_construction():
    c = LoadBearingCertificate(
        task_id="t",
        action_id="a",
        surface_id="tool_call",
        behavior_passed=True,
        load_score=0.5,
        decision="allow",
    )
    assert c.decision == "allow"
    assert 0.0 <= c.load_score <= 1.0


def test_action_proposal_extras():
    ap = ActionProposal(
        action_id="a", surface_id="tool_call", action_type="answer",
        payload={"value": "x"},
    )
    assert ap.payload["value"] == "x"


def test_gate_result_defaults():
    g = GateResult(gate_name="g", passed=True, score=1.0, reason="ok")
    assert g.gate_kind == "validator"
    assert g.weight == 1.0
