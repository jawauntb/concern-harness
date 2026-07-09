"""Tests for the event-sourced concern ledger."""

from __future__ import annotations

from lbah.core import (
    CommitmentSurface,
    ConcernLedger,
    ConcernVariable,
    ConcernEventLog,
    TaskSpec,
    events_from_ledger,
    gauge_fixing_probe,
)


def _task() -> TaskSpec:
    return TaskSpec(task_id="t1", task_type="tool_use", instruction="do the thing")


def _log() -> ConcernEventLog:
    return ConcernEventLog(task=_task())


def test_append_assigns_monotonic_seqs():
    log = _log()
    e1 = log.append("declare_variable", variable_id="a", payload={"name": "A", "concern": 0.9, "source": "task"})
    e2 = log.append("declare_variable", variable_id="b", payload={"name": "B", "concern": 0.5, "source": "task"})
    assert (e1.seq, e2.seq) == (1, 2)


def test_projection_folds_declare_and_revise_last_write_wins():
    log = _log()
    log.append("declare_variable", variable_id="a", payload={"name": "A", "concern": 0.4, "source": "task", "value": "first"})
    log.append("revise_variable", variable_id="a", payload={"value": "second", "concern": 0.8})

    ledger = log.project()
    assert isinstance(ledger, ConcernLedger)
    var = ledger.by_id("a")
    assert var is not None
    # A revise is a new event, not a mutation — the projection reflects the fold.
    assert var.value == "second"
    assert var.concern == 0.8
    # ...and the original value is still recoverable from the log itself.
    assert log.lineage("a")[0].payload["value"] == "first"


def test_revise_does_not_lose_history_unlike_merge():
    """The whole point: a downgrade is recorded, not silently dropped."""
    log = _log()
    log.append("declare_variable", variable_id="a", payload={"name": "A", "concern": 0.9, "source": "task"})
    log.append("revise_variable", variable_id="a", payload={"concern": 0.2})

    assert log.project().by_id("a").concern == 0.2
    assert [e.type for e in log.lineage("a")] == ["declare_variable", "revise_variable"]


def test_set_freshness_event_projects():
    log = _log()
    log.append("declare_variable", variable_id="a", payload={"name": "A", "concern": 0.9, "source": "task"})
    log.append("set_freshness", variable_id="a", payload={"freshness": 0.1})
    assert log.project().by_id("a").freshness == 0.1


def test_add_surface_projects():
    log = _log()
    log.append("add_surface", surface_id="s1", payload={"name": "answer", "type": "final_answer"})
    ledger = log.project()
    assert ledger.surface_by_id("s1") is not None
    assert ledger.surface_by_id("s1").type == "final_answer"


def test_note_has_no_projection_effect():
    log = _log()
    log.append("note", payload={"msg": "reopened by governor"}, source="reopenability_governor")
    ledger = log.project()
    assert ledger.variables == []
    assert len(log.events) == 1


def test_fork_at_truncates_and_records_lineage():
    log = _log()
    log.append("declare_variable", variable_id="a", payload={"name": "A", "concern": 0.9, "source": "task", "value": "x"})
    log.append("declare_variable", variable_id="b", payload={"name": "B", "concern": 0.5, "source": "task"})

    branch = log.fork_at(1)
    assert [e.seq for e in branch.events] == [1]
    assert branch.forked_from == "root"
    assert branch.fork_seq == 1
    # The parent is untouched.
    assert len(log.events) == 2
    # Appends on the branch continue past the fork point with no seq collision.
    ev = branch.append("revise_variable", variable_id="a", payload={"value": "y"})
    assert ev.seq == 2
    assert log.project().by_id("a").value == "x"
    assert branch.project().by_id("a").value == "y"


def test_diff_reports_added_and_changed():
    base = _log()
    base.append("declare_variable", variable_id="a", payload={"name": "A", "concern": 0.9, "source": "task", "value": "x"})

    other = base.fork_at(1)
    other.append("revise_variable", variable_id="a", payload={"value": "y"})
    other.append("declare_variable", variable_id="b", payload={"name": "B", "concern": 0.3, "source": "task"})

    d = base.diff(other)
    assert d.added_variables == ["b"]
    assert d.removed_variables == []
    assert any(c.field == "value" and c.before == "x" and c.after == "y" for c in d.changed)
    assert not d.is_empty


def test_events_from_ledger_roundtrips():
    ledger = ConcernLedger(
        task=_task(),
        variables=[
            ConcernVariable(id="a", name="A", concern=0.9, source="task", value="x"),
            ConcernVariable(id="b", name="B", concern=0.4, source="task"),
        ],
        surfaces=[CommitmentSurface(id="s1", name="answer", type="final_answer")],
    )
    log = events_from_ledger(ledger)
    projected = log.project()
    assert [v.id for v in projected.variables] == ["a", "b"]
    assert projected.by_id("a").value == "x"
    assert projected.surface_by_id("s1").type == "final_answer"


def test_projection_is_deterministic():
    log = _log()
    log.append("declare_variable", variable_id="a", payload={"name": "A", "concern": 0.9, "source": "task", "value": "x"})
    log.append("revise_variable", variable_id="a", payload={"value": "y"})
    assert log.project().model_dump() == log.project().model_dump()


# -- gauge-fixing probe ----------------------------------------------------


def _commit_uses_a(ledger: ConcernLedger):
    """A commitment that genuinely depends on variable 'a'."""
    return {"answer": ledger.by_id("a").value}


def _commit_ignores_a(ledger: ConcernLedger):
    """A commitment invariant to 'a' — the decodability-is-not-load case."""
    return {"answer": "constant"}


def test_gauge_probe_passes_when_commitment_depends_on_variable():
    log = _log()
    log.append("declare_variable", variable_id="a", payload={"name": "A", "concern": 0.9, "source": "task", "value": "real"})

    result = gauge_fixing_probe(log, "a", proxy_value="decoy", commit_fn=_commit_uses_a)
    assert result.commitment_changed is True
    assert result.base_commitment == {"answer": "real"}
    assert result.alt_commitment == {"answer": "decoy"}
    gate = result.as_gate_result()
    assert gate.passed is True
    assert gate.gate_kind == "proxy"
    # The parent log is not mutated by the probe.
    assert log.project().by_id("a").value == "real"


def test_gauge_probe_fails_when_commitment_is_invariant():
    log = _log()
    log.append("declare_variable", variable_id="a", payload={"name": "A", "concern": 0.9, "source": "task", "value": "real"})

    result = gauge_fixing_probe(log, "a", proxy_value="decoy", commit_fn=_commit_ignores_a)
    assert result.commitment_changed is False
    gate = result.as_gate_result()
    assert gate.passed is False
    assert gate.concern_id == "a"
    assert "decodability-is-not-load" in gate.reason


def test_gauge_probe_raises_on_unknown_variable():
    log = _log()
    try:
        gauge_fixing_probe(log, "missing", proxy_value="x", commit_fn=_commit_uses_a)
    except KeyError as exc:
        assert "missing" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected KeyError for unknown variable")
