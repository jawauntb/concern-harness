"""Gauge-fixing probe wired through the ProxyAdversary and the runner."""

from __future__ import annotations

from lbah.adapters.dummy import DummyAgent
from lbah.core.events import ConcernEventLog, events_from_ledger
from lbah.core.runner import HarnessModules, LoadBearingHarness
from lbah.core.schemas import (
    ActionProposal,
    CommitmentSurface,
    ConcernLedger,
    ConcernVariable,
    State,
    TaskSpec,
)
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


def _task() -> TaskSpec:
    return TaskSpec(task_id="t", task_type="tool_use", instruction="answer")


def _ledger_with_two_vars() -> ConcernLedger:
    return ConcernLedger(
        task=_task(),
        variables=[
            ConcernVariable(id="crit", name="crit", concern=0.9, source="task", value="alpha"),
            ConcernVariable(id="other", name="other", concern=0.8, source="task", value="beta"),
        ],
        surfaces=[CommitmentSurface(id="s", name="answer", type="final_answer")],
    )


# -- ProxyAdversary integration -------------------------------------------


def test_proxy_gauge_gate_passes_for_used_variable():
    ledger = _ledger_with_two_vars()
    log = events_from_ledger(ledger)
    state = State(task_id="t")
    proposal = ActionProposal(action_id="a", surface_id="s", action_type="answer", payload={"value": "alpha"})

    # Commitment depends on 'crit'.
    def commit_fn(projected: ConcernLedger):
        return {"value": projected.by_id("crit").value}

    results = ProxyAdversary().check(
        proposal, ledger, state, None,
        log=log, commit_fn=commit_fn, gauge_budget=2,
    )
    gauge = {r.evidence.get("variable_id"): r for r in results if r.gate_name == "proxy::gauge_fixing"}
    assert gauge["crit"].passed is True
    # 'other' does not affect the commitment -> not load-bearing here.
    assert gauge["other"].passed is False


def test_proxy_gauge_absent_when_budget_zero():
    ledger = _ledger_with_two_vars()
    results = ProxyAdversary().check(proposal_stub(), ledger, State(task_id="t"), None)
    assert not any(r.gate_name == "proxy::gauge_fixing" for r in results)


def proposal_stub() -> ActionProposal:
    return ActionProposal(action_id="a", surface_id="s", action_type="answer", payload={"value": "alpha"})


def test_gauge_alt_value_prefers_distractor():
    ledger = _ledger_with_two_vars()
    alt = ProxyAdversary._gauge_alt_value(ledger.by_id("crit"), ledger)
    assert alt == "beta"  # the other variable's value, not a sentinel


def test_gauge_alt_value_falls_back_to_sentinel():
    ledger = ConcernLedger(
        task=_task(),
        variables=[ConcernVariable(id="only", name="only", concern=0.9, source="task", value="x")],
    )
    alt = ProxyAdversary._gauge_alt_value(ledger.by_id("only"), ledger)
    assert alt == "__gauge_alt__:only"


# -- Runner integration ----------------------------------------------------


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


def _gauge_gates(result):
    return [
        g
        for cert in result.certificates
        for g in (cert.gauge_results or [
            r for r in cert.proxy_results if r.gate_name == "proxy::gauge_fixing"
        ])
    ]


class TopConcernAgent:
    """Agent whose commitment is the value of the highest-concern variable.

    Its commitment genuinely depends on that ledger variable, so the gauge
    probe on it must pass.
    """

    name = "top_concern"
    last_tokens = 0

    def propose_action(self, state, ledger):
        variables = ledger.get("variables") or []
        surfaces = ledger.get("surfaces") or []
        surface_id = surfaces[0]["id"] if surfaces else "final_answer"
        top = max(variables, key=lambda v: v.get("concern", 0.0)) if variables else None
        return ActionProposal(
            action_id=f"a{state.get('step', 0)}",
            surface_id=surface_id,
            action_type="answer",
            payload={"value": top.get("value") if top else None},
            claimed_variables_used=[top["id"]] if top else [],
        )

    def observe(self, observation):
        return None


def _controlled_task() -> TaskSpec:
    return TaskSpec(
        task_id="ctrl",
        task_type="tool_use",
        instruction="use the critical value",
        metadata={
            "concern_variables": [
                {"id": "crit", "name": "crit", "value": "alpha", "concern": 0.95, "source": "task", "required_surfaces": ["tool_call"]},
                {"id": "other", "name": "other", "value": "beta", "concern": 0.6, "source": "task", "required_surfaces": ["tool_call"]},
            ],
            "required_surfaces": [{"id": "tool_call", "name": "tool call", "type": "tool_call"}],
        },
    )


def test_runner_gauge_gate_passes_for_ledger_reading_agent():
    result = LoadBearingHarness(
        TopConcernAgent(), ToolUseEnv(), _modules(), mode="audit", gauge_probe_budget=2
    ).run(_controlled_task())
    gates = {g.evidence.get("variable_id"): g for g in _gauge_gates(result)}
    assert gates, "expected gauge gates when budget > 0"
    # The top-concern variable actually controls this agent's commitment.
    assert gates["crit"].passed is True
    # First-class certificate field must be populated.
    assert any(c.gauge_results for c in result.certificates)


def test_runner_gauge_gate_fails_for_constant_agent():
    # DummyAgent("constant") ignores the ledger entirely -> no variable is
    # load-bearing, so every gauge gate must fail (the proxy is caught).
    result = LoadBearingHarness(
        DummyAgent(policy="constant"), ToolUseEnv(), _modules(),
        mode="audit", gauge_probe_budget=2,
    ).run(_controlled_task())
    gates = _gauge_gates(result)
    assert gates
    assert all(not g.passed for g in gates)
    assert any(c.gauge_results for c in result.certificates)


def test_runner_no_gauge_gates_by_default():
    result = LoadBearingHarness(
        TopConcernAgent(), ToolUseEnv(), _modules(), mode="audit"
    ).run(_controlled_task())
    assert not _gauge_gates(result)


def test_log_projection_tracks_working_ledger_after_reopen():
    """The mirrored log must stay equal to the mutated ledger (freshness path)."""
    ledger = _ledger_with_two_vars()
    log = events_from_ledger(ledger)
    # Simulate the runner's reopen mutation + mirror.
    ledger.by_id("crit").freshness = 0.2
    # (a set_freshness event would be appended by the runner; do it here)
    log.append("set_freshness", variable_id="crit", payload={"freshness": 0.2})
    assert log.project().by_id("crit").freshness == ledger.by_id("crit").freshness
