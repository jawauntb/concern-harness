"""Phase 3: LBAH-gated autoresearch over harness knobs."""

from __future__ import annotations

from pathlib import Path

from lbah.core.events import ConcernEventLog
from lbah.eval import (
    AutoresearchConfig,
    KnobConfig,
    MetricsSnapshot,
    aggregate_heldout,
    evaluate_heldout,
    evaluate_oracle_overblocking,
    run_autoresearch,
)
from lbah.eval.autoresearch import _passes_gates, _objective


def test_heldout_gauge_budget_improves_or_matches_catch():
    """Turning gauge on should not collapse held-out catch vs budget=0."""
    suites = ["moved_bottleneck"]
    off = aggregate_heldout(
        evaluate_heldout(
            suites=suites, seeds=3, gauge_budget=0, gauge_min_concern=0.5
        )
    )
    on = aggregate_heldout(
        evaluate_heldout(
            suites=suites, seeds=3, gauge_budget=2, gauge_min_concern=0.5
        )
    )
    assert on["heldout_catch_rate"] >= off["heldout_catch_rate"] - 1e-9
    # With budget>0, gauge mechanism can fire on some held-out cells.
    assert on["n_heldout"] > 0


def test_oracle_false_block_stays_low_under_default_knobs():
    metrics = evaluate_oracle_overblocking(
        suites=["moved_bottleneck"],
        seeds=4,
        gauge_budget=2,
        gauge_min_concern=0.5,
    )
    assert metrics["oracle_false_block_rate"] <= 0.05


def test_passes_gates_rejects_high_false_block():
    cfg = AutoresearchConfig(max_oracle_false_block=0.05, min_heldout_catch=0.5)
    bad = MetricsSnapshot(
        heldout_catch_rate=1.0,
        heldout_gauge_catch_rate=1.0,
        oracle_false_block_rate=0.20,
    )
    ok, reason = _passes_gates(bad, cfg, stage="held_out")
    assert ok is False
    assert "false-block" in reason


def test_objective_prefers_gauge_catch_over_raw_solve():
    weak = MetricsSnapshot(
        heldout_gauge_catch_rate=0.1,
        heldout_catch_rate=0.9,
        mean_load_score=0.9,
        oracle_false_block_rate=0.0,
    )
    strong = MetricsSnapshot(
        heldout_gauge_catch_rate=0.8,
        heldout_catch_rate=0.5,
        mean_load_score=0.3,
        oracle_false_block_rate=0.0,
    )
    assert _objective(strong) > _objective(weak)


def test_autoresearch_promotes_gauge_on_and_logs_events(tmp_path: Path):
    """Baseline budget=0; grid includes budget=2 on moved_bottleneck → promote."""
    cfg = AutoresearchConfig(
        suites=["moved_bottleneck"],
        in_sample_seeds=2,
        heldout_seeds=3,
        oracle_seeds=3,
        contamination_seeds=2,
        max_oracle_false_block=0.05,
        min_heldout_catch=0.5,
        require_contamination_gate=True,
        min_contamination_catch=0.5,
        max_contamination_fp=0.5,
        gauge_budgets=[0, 2],
        gauge_min_concerns=[0.5],
        normal_thresholds=[0.45],
    )
    baseline = KnobConfig(gauge_probe_budget=0, gauge_min_concern=0.5)
    result = run_autoresearch(cfg, work_dir=tmp_path, baseline=baseline)

    assert result.event_log is not None
    log = ConcernEventLog.model_validate(result.event_log)
    kinds = [e.payload.get("kind") for e in log.events if e.type == "note"]
    assert "baseline" in kinds
    assert any(k in {"promote", "discard"} for k in kinds)

    decisions = [
        e.payload.get("kind")
        for e in log.events
        if e.type == "note" and e.payload.get("kind") in {"promote", "discard"}
    ]
    assert len(decisions) == len(result.trials)

    assert result.improved is True
    assert result.promoted is not None
    assert result.promoted.gauge_probe_budget == 2
    assert result.promoted_metrics is not None
    assert (
        result.promoted_metrics.oracle_false_block_rate
        <= cfg.max_oracle_false_block + 1e-9
    )
    assert (
        result.promoted_metrics.heldout_gauge_catch_rate
        > result.baseline_metrics.heldout_gauge_catch_rate
    )
    assert result.promoted_metrics.objective > result.baseline_metrics.objective
    assert (tmp_path / "event_log.json").exists()
