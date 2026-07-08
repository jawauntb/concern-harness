"""Runner end-to-end tests using the moved-bottleneck suite."""

from lbah.adapters.dummy import DummyAgent, OracleAgent
from lbah.benches import load_suite
from lbah.core.runner import HarnessModules, LoadBearingHarness
from lbah.core.schemas import ActionProposal, TaskSpec
from lbah.environments.tool_use_env import ToolUseEnv
from lbah.modules import (
    CommitmentController,
    ConcernMapper,
    OrchestrationAuditor,
    ProxyAdversary,
    ReopenabilityGovernor,
    SurfaceMapper,
    TransportAuditor,
    Verifier,
)


def _harness(agent, env, mode="guarded"):
    modules = HarnessModules(
        concern_mapper=ConcernMapper(),
        surface_mapper=SurfaceMapper(),
        transport_auditor=TransportAuditor(),
        proxy_adversary=ProxyAdversary(),
        reopenability_governor=ReopenabilityGovernor(),
        verifier=Verifier(),
        commitment_controller=CommitmentController(),
    )
    return LoadBearingHarness(agent, env, modules, mode=mode)


class FixedAgent:
    name = "fixed"
    last_tokens = 0

    def __init__(self, proposal: ActionProposal):
        self.proposal = proposal

    def propose_action(self, state, ledger):
        return self.proposal

    def observe(self, observation):
        return None


def test_oracle_passes_moved_bottleneck():
    suite = load_suite("moved_bottleneck")
    passed = 0
    total = 16
    for seed in range(total):
        task = suite.generate(seed)
        env = suite.make_env()
        agent = OracleAgent()
        result = _harness(agent, env).run(task)
        if result.final_success:
            passed += 1
        assert result.certificates
    assert passed >= total * 0.8, f"oracle passed only {passed}/{total}"


def test_first_slot_hits_transport_gate():
    """The first-slot policy uses slot A regardless of which slot is critical.
    We expect it to succeed only when A is the critical slot."""
    suite = load_suite("moved_bottleneck")
    passed = 0
    for seed in range(16):
        task = suite.generate(seed)
        env = suite.make_env()
        agent = DummyAgent(policy="first_slot", seed=seed)
        result = _harness(agent, env).run(task)
        if result.final_success:
            passed += 1
    # First-slot should not dominate; if it does the test is a nop.
    assert passed < 16


def test_tool_constraints_oracle():
    suite = load_suite("tool_constraints")
    task = suite.generate(3)
    env = suite.make_env()
    agent = OracleAgent()
    result = _harness(agent, env).run(task)
    assert result.final_success
    assert result.transport_score >= 0.8


def test_audit_mode_never_blocks():
    suite = load_suite("moved_bottleneck")
    task = suite.generate(0)
    env = suite.make_env()
    agent = DummyAgent(policy="first_slot", seed=0)
    result = _harness(agent, env, mode="audit").run(task)
    for cert in result.certificates:
        assert cert.decision == "allow"


def test_orchestration_auditor_participates_in_runner_decision():
    task = TaskSpec(
        task_id="needs_trace",
        task_type="tool_use",
        instruction="Use the target file.",
        metadata={
            "requires_orchestration_trace": True,
            "expected_action_type": "answer",
            "expected_payload": {"value": "lbah/core/runner.py"},
            "concern_variables": [
                {
                    "id": "target_file",
                    "name": "target_file",
                    "value": "lbah/core/runner.py",
                    "concern": 0.95,
                    "source": "task",
                    "required_surfaces": ["tool_call"],
                }
            ],
            "required_surfaces": [
                {"id": "tool_call", "name": "tool call", "type": "tool_call"}
            ],
        },
    )
    proposal = ActionProposal(
        action_id="a",
        surface_id="tool_call",
        action_type="answer",
        payload={"value": "lbah/core/runner.py"},
    )
    modules = HarnessModules(
        concern_mapper=ConcernMapper(),
        surface_mapper=SurfaceMapper(),
        transport_auditor=TransportAuditor(),
        proxy_adversary=ProxyAdversary(),
        reopenability_governor=ReopenabilityGovernor(),
        verifier=Verifier(),
        orchestration_auditor=OrchestrationAuditor(),
        commitment_controller=CommitmentController(),
    )
    result = LoadBearingHarness(FixedAgent(proposal), ToolUseEnv(), modules).run(task)
    assert not result.final_success
    assert result.certificates
    assert result.certificates[0].decision == "revise"
    assert "orchestration::trace_present" in result.failed_gates
