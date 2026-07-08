"""Runner end-to-end tests using the moved-bottleneck suite."""

from lbah.adapters.dummy import DummyAgent, OracleAgent
from lbah.benches import load_suite
from lbah.core.runner import HarnessModules, LoadBearingHarness
from lbah.modules import (
    CommitmentController,
    ConcernMapper,
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
