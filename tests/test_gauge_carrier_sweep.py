"""Value-sweep gauge probe: perturb the distinction, not one carrier.

Covers the three-way verdict and the OracleAgent case that a single-node
perturbation mislabeled as a proxy.
"""

from __future__ import annotations

from lbah.adapters.dummy import DummyAgent, OracleAgent
from lbah.core.events import ConcernEventLog, gauge_fixing_probe
from lbah.core.runner import HarnessModules, LoadBearingHarness
from lbah.core.schemas import ActionProposal, TaskSpec
from lbah.environments.tool_use_env import ToolUseEnv
from lbah.modules import (
    CommitmentController,
    ConcernMapper,
    ProxyAdversary,
    ReopenabilityGovernor,
    SurfaceMapper,
    TransportAuditor,
    Verifier,
)


def _log_one(value: str = "alpha") -> ConcernEventLog:
    log = ConcernEventLog(task=TaskSpec(task_id="t", task_type="tool_use", instruction="i"))
    log.append(
        "declare_variable",
        variable_id="a",
        payload={"name": "A", "concern": 0.9, "source": "task", "value": value},
    )
    return log


# -- three-way verdict at the unit level ----------------------------------


def test_verdict_gauge_fixed():
    log = _log_one()
    r = gauge_fixing_probe(log, "a", "decoy", lambda L: {"v": L.by_id("a").value})
    assert r.verdict == "gauge_fixed"
    assert r.commitment_changed is True
    assert r.as_gate_result().passed is True


def test_verdict_invariant_but_value_present():
    # commit_fn hardcodes the value, ignoring the ledger entirely: the value is
    # present in the commitment but tracks no carrier we swept.
    log = _log_one()
    r = gauge_fixing_probe(log, "a", "decoy", lambda L: {"v": "alpha"})
    assert r.verdict == "invariant_but_value_present"
    assert r.value_present is True
    gate = r.as_gate_result()
    assert gate.passed is True  # ambiguous, not an unconditional block
    assert gate.score == 0.75


def test_verdict_invariant_and_absent():
    log = _log_one()
    r = gauge_fixing_probe(log, "a", "decoy", lambda L: {"v": "constant"})
    assert r.verdict == "invariant_and_absent"
    assert r.value_present is False
    gate = r.as_gate_result()
    assert gate.passed is False
    assert "decodability-is-not-load" in gate.reason


def test_sweep_reaches_embedded_task_metadata():
    """The sweep replaces the value in task.metadata, not just the ledger node."""
    log = ConcernEventLog(
        task=TaskSpec(
            task_id="t",
            task_type="tool_use",
            instruction="i",
            metadata={"expected_payload": {"value": "alpha"}},
        )
    )
    log.append(
        "declare_variable",
        variable_id="a",
        payload={"name": "A", "concern": 0.9, "source": "task", "value": "alpha"},
    )

    # commit_fn reads ONLY the metadata carrier, never the ledger variable.
    def commit_fn(L):
        return L.task.metadata["expected_payload"]

    r = gauge_fixing_probe(log, "a", "beta", commit_fn)
    assert r.verdict == "gauge_fixed"
    assert r.alt_commitment == {"value": "beta"}


# -- OracleAgent: the case a single-node probe got wrong -------------------


def _modules() -> HarnessModules:
    return HarnessModules(
        concern_mapper=ConcernMapper(),
        surface_mapper=SurfaceMapper(),
        transport_auditor=TransportAuditor(),
        proxy_adversary=ProxyAdversary(),
        reopenability_governor=ReopenabilityGovernor(),
        verifier=Verifier(),
        commitment_controller=CommitmentController(),
    )


def _oracle_task() -> TaskSpec:
    return TaskSpec(
        task_id="ora",
        task_type="tool_use",
        instruction="return the critical value",
        max_steps=1,
        metadata={
            "concern_variables": [
                {"id": "crit", "name": "crit", "value": "alpha", "concern": 0.95, "source": "task", "required_surfaces": ["tool_call"]},
            ],
            "required_surfaces": [{"id": "tool_call", "name": "tool call", "type": "tool_call"}],
            "expected_payload": {"value": "alpha"},
            "expected_action_type": "answer",
            "critical_variable_ids": ["crit"],
        },
    )


def _gauge_gates(result):
    return [
        g
        for cert in result.certificates
        for g in cert.proxy_results
        if g.gate_name == "proxy::gauge_fixing"
    ]


def test_oracle_agent_now_passes_gauge():
    # OracleAgent reads task.metadata.expected_payload, not the ledger node.
    # The value-sweep reaches that carrier, so its commitment moves and the
    # gauge gate passes instead of falsely flagging it as a proxy.
    result = LoadBearingHarness(
        OracleAgent(), ToolUseEnv(), _modules(), mode="audit", gauge_probe_budget=1
    ).run(_oracle_task())
    gates = {g.evidence.get("variable_id"): g for g in _gauge_gates(result)}
    assert gates, "expected a gauge gate"
    assert gates["crit"].passed is True
    assert gates["crit"].evidence["verdict"] == "gauge_fixed"


class HardcodedAgent:
    """Commits a fixed value regardless of input — a hardcoded 'constant'."""

    name = "hardcoded"
    last_tokens = 0

    def __init__(self, const: str):
        self.const = const

    def propose_action(self, state, ledger):
        surfaces = ledger.get("surfaces") or []
        surface_id = surfaces[0]["id"] if surfaces else "final_answer"
        return ActionProposal(
            action_id=f"a{state.get('step', 0)}",
            surface_id=surface_id,
            action_type="answer",
            payload={"value": self.const},
        )

    def observe(self, observation):
        return None


def test_hardcoded_value_is_flagged_not_blocked():
    # Agent hardcodes "alpha" (== crit's value) but reads nothing. Value present,
    # commitment invariant -> ambiguous middle verdict, flagged but not blocked.
    result = LoadBearingHarness(
        HardcodedAgent("alpha"), ToolUseEnv(), _modules(), mode="audit", gauge_probe_budget=1
    ).run(_oracle_task())
    gates = {g.evidence.get("variable_id"): g for g in _gauge_gates(result)}
    assert gates["crit"].evidence["verdict"] == "invariant_but_value_present"
    assert gates["crit"].passed is True
    assert gates["crit"].score == 0.75
