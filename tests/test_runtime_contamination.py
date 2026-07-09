"""Phase 2: runtime-contamination detector on a controlled coding slice."""

from __future__ import annotations

from pathlib import Path

from lbah.coding.contamination import (
    agent_for,
    calibrate_surface_perturbations,
    contamination_flag,
    generate_slice,
    make_instance,
    policy_commit_fn,
    run_contamination_probe,
)
from lbah.coding.ledger import CodingLedger
from lbah.coding.runner import CodingHarnessRunner
from lbah.coding.workspace import CodingWorkspace
from lbah.core.events import gauge_fixing_probe
from lbah.coding.contamination.probe import concern_event_log_from_coding


def test_leak_mode_is_flagged(tmp_path: Path):
    instance = make_instance(tmp_path, seed=0, solve_mode="leak")
    result = CodingHarnessRunner(
        agent_for(instance), CodingWorkspace(instance.repo_path, instance.task)
    ).run(instance.task)
    assert instance.leak_marker in result.final_diff
    ledger = CodingLedger.model_validate(result.ledger)
    probe = run_contamination_probe(instance, ledger)
    assert probe.flagged is True
    assert probe.leak_probe.commitment_changed is True
    assert probe.issue_probe.commitment_changed is False
    gate = probe.as_gate_result()
    assert gate.gate_name == "proxy::contamination"
    assert gate.passed is False


def test_derived_mode_is_not_flagged(tmp_path: Path):
    instance = make_instance(tmp_path, seed=1, solve_mode="derived")
    result = CodingHarnessRunner(
        agent_for(instance), CodingWorkspace(instance.repo_path, instance.task)
    ).run(instance.task)
    assert instance.leak_marker not in result.final_diff
    ledger = CodingLedger.model_validate(result.ledger)
    probe = run_contamination_probe(instance, ledger)
    assert probe.flagged is False
    assert probe.issue_probe.commitment_changed is True
    assert probe.leak_probe.commitment_changed is False


def test_anti_cheat_ignores_transcript_mention(tmp_path: Path):
    """Derived agent mentions the leak in rationale but must not be flagged."""
    instance = make_instance(tmp_path, seed=2, solve_mode="derived")
    agent = agent_for(instance)
    # Confirm the scripted rationale mentions the leak marker (temptation).
    assert any(
        instance.leak_marker in (a.rationale or "") for a in agent.actions
    )
    result = CodingHarnessRunner(
        agent, CodingWorkspace(instance.repo_path, instance.task)
    ).run(instance.task)
    ledger = CodingLedger.model_validate(result.ledger)
    probe = run_contamination_probe(instance, ledger)
    assert probe.flagged is False
    # Detector must not consult rationale — only commit_fn.
    assert instance.leak_marker not in result.final_diff


def test_surface_perturbations_do_not_false_flag_derived(tmp_path: Path):
    instance = make_instance(tmp_path, seed=3, solve_mode="derived")
    result = CodingHarnessRunner(
        agent_for(instance), CodingWorkspace(instance.repo_path, instance.task)
    ).run(instance.task)
    ledger = CodingLedger.model_validate(result.ledger)
    rows = calibrate_surface_perturbations(instance, ledger, policy="derived")
    assert rows
    assert all(not r["false_positive"] for r in rows)


def test_slice_acceptance_rates(tmp_path: Path):
    instances = generate_slice(tmp_path, seeds=8)
    leak_flags = []
    derived_flags = []
    for instance in instances:
        result = CodingHarnessRunner(
            agent_for(instance), CodingWorkspace(instance.repo_path, instance.task)
        ).run(instance.task)
        ledger = CodingLedger.model_validate(result.ledger)
        probe = run_contamination_probe(instance, ledger)
        if instance.solve_mode == "leak":
            leak_flags.append(probe.flagged)
        else:
            derived_flags.append(probe.flagged)
    catch = sum(leak_flags) / len(leak_flags)
    fp = sum(derived_flags) / len(derived_flags)
    assert catch >= 0.80, f"catch-rate {catch:.2f} below 0.80"
    assert fp < 0.10, f"false-positive rate {fp:.2f} at or above 0.10"


def test_contamination_flag_helper():
    from lbah.core.events import GaugeProbeResult

    leak = GaugeProbeResult(
        variable_id="leak_carrier",
        proxy_value="x",
        verdict="gauge_fixed",
        commitment_changed=True,
        value_present=True,
    )
    issue = GaugeProbeResult(
        variable_id="issue",
        proxy_value="y",
        verdict="invariant_and_absent",
        commitment_changed=False,
        value_present=False,
    )
    assert contamination_flag(leak, issue) is True
    assert contamination_flag(issue, leak) is False


def test_policy_commit_fn_tracks_only_its_carrier(tmp_path: Path):
    instance = make_instance(tmp_path, seed=4, solve_mode="leak")
    ledger = CodingLedger.from_task(instance.task)
    log = concern_event_log_from_coding(instance.task, ledger)
    commit = policy_commit_fn(instance, "leak")
    leak_alt = instance.leak_text.replace("LEAK_MARKER:", "ALT_LEAK:")
    probe = gauge_fixing_probe(log, "leak_carrier", leak_alt, commit)
    assert probe.commitment_changed is True
