"""Phase 0: CLI gauge wiring, certificate gauge_results, telemetry coverage."""

from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from lbah.cli import _mode_defaults, _resolve_gauge, _run_result_row, cli
from lbah.core.certificates import make_certificate
from lbah.core.diagnostics import COMPONENT_SCORE_KEYS, summarize_runs
from lbah.core.schemas import (
    ActionProposal,
    CommitmentSurface,
    ConcernLedger,
    ConcernVariable,
    GateResult,
    LoadBearingCertificate,
    RunResult,
    State,
    TaskSpec,
)
from lbah.core.scorer import Scorer


def test_mode_yaml_defaults_include_gauge_budget():
    guarded = _mode_defaults("guarded")
    audit = _mode_defaults("audit")
    assert guarded.get("gauge_probe_budget", 0) > 0
    assert audit.get("gauge_probe_budget", 0) > 0
    assert 0.0 <= float(guarded.get("gauge_min_concern", 0.5)) <= 1.0


def test_resolve_gauge_cli_overrides_mode_yaml():
    thresholds, budget, min_c = _resolve_gauge("guarded", 7, 0.9, {"normal": 0.4})
    assert budget == 7
    assert min_c == 0.9
    assert thresholds["normal"] == 0.4


def test_resolve_gauge_falls_back_to_mode_yaml():
    _, budget, min_c = _resolve_gauge("guarded", None, None, {})
    assert budget == int(_mode_defaults("guarded")["gauge_probe_budget"])
    assert min_c == float(_mode_defaults("guarded")["gauge_min_concern"])


def test_make_certificate_populates_gauge_results():
    task = TaskSpec(task_id="t", task_type="tool_use", instruction="")
    ledger = ConcernLedger(
        task=task,
        variables=[ConcernVariable(id="v", name="v", concern=1.0, source="task")],
        surfaces=[CommitmentSurface(id="s", name="s", type="final_answer")],
    )
    proposal = ActionProposal(action_id="a", surface_id="s", action_type="answer", payload={})
    gauge = GateResult(
        gate_name="proxy::gauge_fixing",
        gate_kind="proxy",
        passed=False,
        score=0.0,
        reason="invariant",
        evidence={"verdict": "invariant_and_absent", "variable_id": "v"},
        concern_id="v",
        weight=1.0,
    )
    static = GateResult(
        gate_name="proxy::static",
        gate_kind="proxy",
        passed=True,
        score=1.0,
        reason="ok",
    )
    cert = make_certificate(
        task=task,
        ledger=ledger,
        proposal=proposal,
        transport=[],
        proxy=[static, gauge],
        reopen=[],
        validators=[],
    )
    assert len(cert.gauge_results) == 1
    assert cert.gauge_results[0].evidence["verdict"] == "invariant_and_absent"
    assert len(cert.proxy_results) == 2  # backward compatible


def test_run_result_row_has_all_component_scores():
    result = RunResult(
        task_id="t",
        agent="a",
        mode="guarded",
        final_success=True,
        final_state={},
        load_score=0.5,
        behavior_score=1.0,
        transport_score=0.8,
        proxy_resistance_score=0.7,
        reopenability_score=1.0,
        commitment_validity_score=0.9,
        certificates=[],
    )
    row = _run_result_row(
        run_id="r1", task_id="t", agent="a", mode="guarded", result=result
    )
    for key in COMPONENT_SCORE_KEYS:
        assert key in row and row[key] is not None


def test_summarize_runs_reports_full_component_coverage():
    rows = [
        {
            "agent": "a",
            "mode": "guarded",
            "final_success": True,
            "load_score": 0.5,
            "behavior_score": 1.0,
            "transport_score": 0.8,
            "proxy_resistance_score": 0.7,
            "reopenability_score": 1.0,
            "commitment_validity_score": 0.9,
            "tokens": 1,
            "failed_gates": [],
        }
    ]
    summary = summarize_runs(rows)
    assert summary["configs"][0]["component_score_coverage"] == 1.0
    assert summary["configs"][0]["behavior_score_mean"] == 1.0


def test_scorer_includes_gauge_failures_in_failed_gates():
    cert = LoadBearingCertificate(
        task_id="t",
        action_id="a",
        surface_id="s",
        behavior_passed=True,
        load_score=0.5,
        decision="revise",
        gauge_results=[
            GateResult(
                gate_name="proxy::gauge_fixing",
                gate_kind="proxy",
                passed=False,
                score=0.0,
                reason="fail",
            )
        ],
    )
    result = Scorer().score(
        TaskSpec(task_id="t", task_type="tool_use", instruction=""),
        "agent",
        "audit",
        State(task_id="t"),
        [cert],
    )
    assert "proxy::gauge_fixing" in result.failed_gates


def test_cli_bench_fires_gauge_and_persists_components(tmp_path: Path):
    runner = CliRunner()
    out = tmp_path / "bench"
    result = runner.invoke(
        cli,
        [
            "bench",
            "--suite",
            "moved_bottleneck",
            "--agent",
            "configs/oracle.yaml",
            "--mode",
            "audit",
            "--seeds",
            "2",
            "--gauge-budget",
            "2",
            "--out",
            str(out),
        ],
    )
    assert result.exit_code == 0, result.output
    rows = [json.loads(line) for line in (out / "runs.jsonl").read_text().splitlines() if line]
    assert len(rows) == 2
    for row in rows:
        for key in COMPONENT_SCORE_KEYS:
            assert row.get(key) is not None, f"missing {key}"
        assert row.get("gauge_gate_count", 0) > 0
