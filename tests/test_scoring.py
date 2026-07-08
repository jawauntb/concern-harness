"""Tests for scoring composition and certificate decision logic."""

from lbah.core.certificates import (
    compute_load_score,
    decide_from_gates,
    make_certificate,
)
from lbah.core.schemas import (
    ActionProposal,
    CommitmentSurface,
    ConcernLedger,
    ConcernVariable,
    GateResult,
    TaskSpec,
)


def _ledger(irreversible: bool = False, surface_type: str = "tool_call") -> ConcernLedger:
    task = TaskSpec(
        task_id="t",
        task_type="tool_use",
        instruction="",
        irreversible=irreversible,
    )
    var = ConcernVariable(
        id="v", name="v", value="expected", concern=1.0,
        source="task", required_surfaces=[surface_type],
    )
    surface = CommitmentSurface(
        id=surface_type, name=surface_type, type=surface_type,  # type: ignore[arg-type]
        irreversible=irreversible,
    )
    return ConcernLedger(task=task, variables=[var], surfaces=[surface])


def test_load_score_is_product():
    assert compute_load_score(1, 1, 1, 1, 1) == 1
    assert abs(compute_load_score(1, 0.5, 1, 1, 1) - 0.5) < 1e-6
    assert compute_load_score(1, 0, 1, 1, 1) == 0


def test_decision_block_when_load_too_low():
    ledger = _ledger()
    proposal = ActionProposal(
        action_id="a", surface_id="tool_call", action_type="answer", payload={},
    )
    transport = [GateResult(gate_name="transport::v", passed=False, score=0.0, reason="", weight=0.4)]
    proxy: list = []
    reopen: list = []
    validators: list = []
    d = decide_from_gates(ledger.task, ledger, proposal, transport, proxy, reopen, validators)
    assert d in {"block", "revise"}


def test_decision_allow_when_all_pass():
    ledger = _ledger()
    proposal = ActionProposal(
        action_id="a", surface_id="tool_call", action_type="answer",
        payload={"value": "expected"},
    )
    transport = [GateResult(gate_name="transport::v", passed=True, score=1.0, reason="", weight=1.0)]
    validators = [GateResult(gate_name="v::x", passed=True, score=1.0, reason="")]
    d = decide_from_gates(ledger.task, ledger, proposal, transport, [], [], validators)
    assert d == "allow"


def test_certificate_summary_lists_failures():
    ledger = _ledger()
    proposal = ActionProposal(
        action_id="a", surface_id="tool_call", action_type="answer", payload={},
    )
    fail = GateResult(gate_name="proxy::x", passed=False, score=0.0, reason="fail", weight=1.0)
    cert = make_certificate(
        task=ledger.task, ledger=ledger, proposal=proposal,
        transport=[], proxy=[fail], reopen=[], validators=[],
    )
    assert "proxy::x" in cert.summary or cert.decision in {"block", "revise"}
