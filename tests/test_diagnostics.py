"""Tests for run diagnostics and harness-evolution proposals."""

from lbah.core.diagnostics import (
    gate_family,
    improvement_proposals,
    markdown_report,
    summarize_runs,
)


def test_gate_family_classifies_orchestration_prefix():
    assert gate_family("orchestration::transport::target_file") == "orchestration"
    assert gate_family("proxy::wrong_slot") == "proxy"


def test_summarize_runs_groups_model_harness_configs():
    rows = [
        {
            "agent": "fugu",
            "mode": "audit",
            "final_success": True,
            "load_score": 0.8,
            "transport_score": 0.7,
            "proxy_resistance_score": 1.0,
            "reopenability_score": 1.0,
            "commitment_validity_score": 0.9,
            "tokens": 10,
            "failed_gates": ["transport::target_file"],
        },
        {
            "agent": "fugu",
            "mode": "audit",
            "final_success": False,
            "load_score": 0.2,
            "transport_score": 0.0,
            "proxy_resistance_score": 1.0,
            "reopenability_score": 1.0,
            "commitment_validity_score": 0.9,
            "tokens": 20,
            "failed_gates": ["orchestration::transport::target_file"],
        },
    ]
    summary = summarize_runs(rows)
    assert summary["configs"][0]["final_success_rate"] == 0.5
    assert summary["failed_gate_family_counts"]["transport"] == 1
    assert summary["failed_gate_family_counts"]["orchestration"] == 1


def test_improvement_proposals_are_actionable():
    rows = [{"failed_gates": ["proxy::wrong_slot"], "agent": "a", "mode": "guarded"}]
    proposals = improvement_proposals(rows)
    assert proposals
    assert proposals[0]["family"] == "proxy"
    assert "gauge" in proposals[0]["title"].lower()


def test_markdown_report_contains_config_and_proposal_sections():
    report = markdown_report(
        [{"failed_gates": ["validator::schema_valid"], "agent": "a", "mode": "guarded"}]
    )
    assert "Model-Harness Configurations" in report
    assert "Improvement Proposals" in report
