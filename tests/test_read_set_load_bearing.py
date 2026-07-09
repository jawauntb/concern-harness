"""Read-set load-bearingness (Law 2 at the coding surface)."""

from __future__ import annotations

import statistics
from pathlib import Path

from lbah.coding.contamination import (
    generate_read_set_slice,
    make_read_set_instance,
    read_set_agent,
    read_set_commit_fn,
    run_read_set_probe,
)
from lbah.coding.contamination.read_set import concern_event_log_from_instance
from lbah.core.events import gauge_fixing_probe


def test_true_load_bearing_read_flagged(tmp_path: Path):
    """The ground-truth issue-derived read must be flagged load_bearing."""
    instance = make_read_set_instance(tmp_path, seed=0)
    result = run_read_set_probe(instance)
    verdict_by_id = {v.read_id: v for v in result.per_read}
    assert "read_0" in verdict_by_id, "expected read_0 in probe results"
    assert verdict_by_id["read_0"].verdict == "load_bearing", (
        f"true load-bearing read_0 flagged {verdict_by_id['read_0'].verdict!r} "
        f"instead of load_bearing"
    )
    assert verdict_by_id["read_0"].commitment_changed is True
    assert "read_0" in result.predicted_load_bearing


def test_distractor_reads_marked_redundant(tmp_path: Path):
    """Every non-truth read must be marked redundant."""
    instance = make_read_set_instance(tmp_path, seed=1, reads_per_task=4)
    result = run_read_set_probe(instance)
    for v in result.per_read:
        if v.read_id == "read_0":
            continue
        assert v.verdict == "redundant", (
            f"distractor {v.read_id} ({v.kind}) incorrectly flagged {v.verdict}"
        )
        assert v.commitment_changed is False


def test_perfect_recall_at_default_settings(tmp_path: Path):
    """Macro F1 across the default slice must be at least 0.95."""
    instances = generate_read_set_slice(tmp_path, seeds=8, reads_per_task=4)
    f1s: list[float] = []
    precisions: list[float] = []
    recalls: list[float] = []
    for instance in instances:
        result = run_read_set_probe(instance)
        f1s.append(result.set_f1)
        precisions.append(result.set_precision)
        recalls.append(result.set_recall)
    macro_f1 = statistics.mean(f1s)
    macro_p = statistics.mean(precisions)
    macro_r = statistics.mean(recalls)
    assert macro_f1 >= 0.95, f"macro F1 {macro_f1:.3f} below 0.95"
    assert macro_p >= 0.95, f"macro precision {macro_p:.3f} below 0.95"
    assert macro_r >= 0.95, f"macro recall {macro_r:.3f} below 0.95"


def test_commit_fn_only_tracks_true_load_bearing(tmp_path: Path):
    """Direct gauge_fixing_probe: LB read flips commitment, distractor does not."""
    instance = make_read_set_instance(tmp_path, seed=2, reads_per_task=4)
    log = concern_event_log_from_instance(instance)
    commit = read_set_commit_fn(instance)

    projected = log.project()
    lb_var = projected.by_id("read_0")
    distractor_var = projected.by_id("read_2")
    assert lb_var is not None and distractor_var is not None

    lb_probe = gauge_fixing_probe(
        log, "read_0", f"{lb_var.value}::ALT_read_0_seed_2", commit
    )
    distractor_probe = gauge_fixing_probe(
        log, "read_2", f"{distractor_var.value}::ALT_read_2_seed_2", commit
    )
    assert lb_probe.commitment_changed is True
    assert distractor_probe.commitment_changed is False


def test_read_set_agent_shape(tmp_path: Path):
    """The scripted read-set agent reads each carrier and applies the edit."""
    instance = make_read_set_instance(tmp_path, seed=3, reads_per_task=4)
    agent = read_set_agent(instance)
    read_actions = [a for a in agent.actions if a.action_type == "read_file"]
    assert len(read_actions) == len(instance.reads)
    edits = [a for a in agent.actions if a.action_type == "edit_file"]
    assert edits and edits[0].payload.get("new") == instance.derived_line
