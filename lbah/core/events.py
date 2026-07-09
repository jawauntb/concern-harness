"""Event-sourced concern ledger.

The base harness keeps its live state in a :class:`ConcernLedger`, which is
mutated in place (see ``core/ledger.merge_variables``). That is convenient but
lossy: once a concern variable is overwritten its prior value is gone, so the
question the harness actually cares about — *did this distinction survive from
perception to commitment?* — has to be reconstructed rather than read off.

This module makes the ledger an **append-only event log** with the existing
``ConcernLedger`` as a deterministic *projection* of that log. Nothing is ever
overwritten; a revision is a new event. That buys three things the four
obligations in ``docs/THEORY.md`` already want:

* **Transport** becomes a lineage query — :meth:`ConcernEventLog.lineage`
  returns every event that touched a variable, in order, so provenance is
  read rather than inferred.
* **Gauge-fixing** becomes a real intervention — :meth:`ConcernEventLog.fork_at`
  branches the log at the event where a variable was set, and
  :func:`gauge_fixing_probe` perturbs it to a gauge-equivalent proxy value,
  re-projects, and diffs the resulting commitment. If the commitment is
  unchanged, the `decodability-is-not-load` law fires.
* **Reopenability** becomes a freshness event over a temporal log rather than
  an in-place field poke.

The models are pure and deterministic: projection is seq-ordered and never
consults wall-clock time. ``ts`` is optional provenance metadata and plays no
part in the fold, so replays are reproducible.
"""

from __future__ import annotations

from typing import Any, Callable, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from .schemas import (
    CommitmentSurface,
    ConcernLedger,
    ConcernVariable,
    GateResult,
    TaskSpec,
)


EventType = Literal[
    "declare_variable",  # a concern variable enters the ledger for the first time
    "revise_variable",   # one or more fields of an existing variable change
    "set_freshness",     # freshness-only update (staleness decay / reopen)
    "perturb_variable",  # counterfactual value swap; used by gauge-fixing forks
    "add_surface",       # a commitment surface is identified
    "note",              # free-form provenance marker, no projection effect
]


class ConcernEvent(BaseModel):
    """A single append-only change to the concern state.

    ``payload`` holds the partial fields being set on the referenced variable
    or surface (last-write-wins per field during projection).
    """

    seq: int
    type: EventType
    variable_id: str | None = None
    surface_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    source: str = ""  # which module/surface emitted it — provenance, not identity
    ts: float | None = None  # optional wall-clock; ignored by projection


class VariableDelta(BaseModel):
    """How a single variable differs between two projections."""

    variable_id: str
    field: str
    before: Any | None = None
    after: Any | None = None


class LedgerDiff(BaseModel):
    """Structural diff between two ledger projections."""

    added_variables: list[str] = Field(default_factory=list)
    removed_variables: list[str] = Field(default_factory=list)
    changed: list[VariableDelta] = Field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not (self.added_variables or self.removed_variables or self.changed)


# Fields compared when diffing two projections of the same variable id.
_DIFFED_FIELDS = ("value", "concern", "freshness", "source", "name")


class ConcernEventLog(BaseModel):
    """Append-only log of concern events; the ledger is its projection."""

    model_config = ConfigDict(extra="allow")

    task: TaskSpec
    events: list[ConcernEvent] = Field(default_factory=list)
    forked_from: str | None = None  # label of the parent log, if this is a branch
    fork_seq: int | None = None     # seq at which this branch diverged from its parent
    label: str = "root"

    # -- writing -------------------------------------------------------------

    def _next_seq(self) -> int:
        return (max((e.seq for e in self.events), default=0)) + 1

    def append(
        self,
        type: EventType,
        *,
        variable_id: str | None = None,
        surface_id: str | None = None,
        payload: dict[str, Any] | None = None,
        source: str = "",
        ts: float | None = None,
    ) -> ConcernEvent:
        """Append one event and return it (with its assigned seq)."""
        event = ConcernEvent(
            seq=self._next_seq(),
            type=type,
            variable_id=variable_id,
            surface_id=surface_id,
            payload=dict(payload or {}),
            source=source,
            ts=ts,
        )
        self.events.append(event)
        return event

    # -- reading -------------------------------------------------------------

    def project(self) -> ConcernLedger:
        """Fold the events into a :class:`ConcernLedger` (seq order, LWW per field)."""
        variables: dict[str, ConcernVariable] = {}
        var_order: list[str] = []
        surfaces: dict[str, CommitmentSurface] = {}
        surface_order: list[str] = []

        for event in sorted(self.events, key=lambda e: e.seq):
            if event.type == "add_surface":
                sid = event.surface_id or event.payload.get("id")
                if sid is None:
                    continue
                if sid in surfaces:
                    surfaces[sid] = surfaces[sid].model_copy(update=event.payload)
                else:
                    fields = {k: v for k, v in event.payload.items() if k != "id"}
                    surfaces[sid] = CommitmentSurface(id=sid, **fields)
                    surface_order.append(sid)
                continue

            if event.type == "note":
                continue

            vid = event.variable_id or event.payload.get("id")
            if vid is None:
                continue

            if vid in variables:
                update = {k: v for k, v in event.payload.items() if k != "id"}
                variables[vid] = variables[vid].model_copy(update=update)
            else:
                # First time we see this id — declare it. Non-declare events on
                # an unknown id still create it, so a projection never silently
                # drops information; the payload must carry the required fields.
                fields = {k: v for k, v in event.payload.items() if k != "id"}
                variables[vid] = ConcernVariable(id=vid, **fields)
                var_order.append(vid)

        return ConcernLedger(
            task=self.task,
            variables=[variables[v] for v in var_order],
            surfaces=[surfaces[s] for s in surface_order],
            updates=[e.model_dump() for e in sorted(self.events, key=lambda e: e.seq)],
        )

    def lineage(self, variable_id: str) -> list[ConcernEvent]:
        """Every event that touched ``variable_id``, in seq order — its provenance."""
        return [
            e
            for e in sorted(self.events, key=lambda e: e.seq)
            if e.variable_id == variable_id
        ]

    # -- branching -----------------------------------------------------------

    def fork_at(self, seq: int, *, label: str | None = None) -> "ConcernEventLog":
        """Branch a new log containing every event with ``e.seq <= seq``.

        The gauge-fixing point for a variable is the seq of the last event that
        set it (see :meth:`lineage`). Forking there lets a probe replay the run
        with a single distinction changed and everything downstream re-derived.
        """
        kept = [e.model_copy(deep=True) for e in self.events if e.seq <= seq]
        return ConcernEventLog(
            task=self.task,
            events=kept,
            forked_from=self.label,
            fork_seq=seq,
            label=label or f"{self.label}@{seq}",
        )

    def diff(self, other: "ConcernEventLog") -> LedgerDiff:
        """Diff this log's projection against ``other``'s (self = before)."""
        before = {v.id: v for v in self.project().variables}
        after = {v.id: v for v in other.project().variables}

        added = [vid for vid in after if vid not in before]
        removed = [vid for vid in before if vid not in after]
        changed: list[VariableDelta] = []
        for vid in before:
            if vid not in after:
                continue
            b, a = before[vid], after[vid]
            for field in _DIFFED_FIELDS:
                bv, av = getattr(b, field), getattr(a, field)
                if bv != av:
                    changed.append(
                        VariableDelta(variable_id=vid, field=field, before=bv, after=av)
                    )
        return LedgerDiff(
            added_variables=sorted(added),
            removed_variables=sorted(removed),
            changed=changed,
        )


def events_from_ledger(ledger: ConcernLedger) -> ConcernEventLog:
    """Bootstrap an event log from an existing (mutable) ledger.

    This is the migration seam: current code that builds a ``ConcernLedger`` up
    front can hand it here and get an event log whose projection is equal to
    the original ledger (modulo the reconstructed ``updates`` trail).
    """
    log = ConcernEventLog(task=ledger.task)
    for var in ledger.variables:
        log.append(
            "declare_variable",
            variable_id=var.id,
            payload=var.model_dump(),
            source=var.source,
        )
    for surface in ledger.surfaces:
        log.append(
            "add_surface",
            surface_id=surface.id,
            payload=surface.model_dump(),
            source="surface_mapper",
        )
    return log


class GaugeProbeResult(BaseModel):
    """Outcome of a counterfactual gauge-fixing probe."""

    variable_id: str
    proxy_value: Any | None
    fork_seq: int
    commitment_changed: bool
    base_commitment: Any | None = None
    alt_commitment: Any | None = None

    def as_gate_result(self) -> GateResult:
        """A proxy gate: the claim is identified only if the commitment moved.

        ``passed`` is True when perturbing the variable to a gauge-equivalent
        proxy value *changed* the commitment. An unchanged commitment means the
        distinction did no work — `decodability-is-not-load`.
        """
        return GateResult(
            gate_name="proxy::gauge_fixing",
            gate_kind="proxy",
            passed=self.commitment_changed,
            score=1.0 if self.commitment_changed else 0.0,
            reason=(
                f"commitment changed when {self.variable_id} was perturbed — gauge fixed"
                if self.commitment_changed
                else (
                    f"commitment invariant to {self.variable_id}; distinction is not "
                    "load-bearing (decodability-is-not-load)"
                )
            ),
            evidence={
                "variable_id": self.variable_id,
                "proxy_value": self.proxy_value,
                "fork_seq": self.fork_seq,
            },
            concern_id=self.variable_id,
            weight=1.0,
        )


def gauge_fixing_probe(
    log: ConcernEventLog,
    variable_id: str,
    proxy_value: Any,
    commit_fn: Callable[[ConcernLedger], Any],
    *,
    at_seq: Optional[int] = None,
) -> GaugeProbeResult:
    """Run a gauge-fixing intervention on ``variable_id``.

    ``commit_fn`` maps a ledger projection to the commitment the system would
    make from it (in real use, the agent proposing an action; in tests, any
    deterministic function). The probe:

    1. forks the log at the point the variable was last set (``at_seq``, or the
       seq of its most recent lineage event),
    2. appends a ``perturb_variable`` event swapping in ``proxy_value``,
    3. projects both logs and compares ``commit_fn`` on each.

    If the commitment is invariant to the swap, the distinction is a gauge
    freedom, not a load-bearing variable.
    """
    lineage = log.lineage(variable_id)
    if not lineage:
        raise KeyError(f"variable {variable_id!r} has no events to fork from")
    fork_seq = at_seq if at_seq is not None else lineage[-1].seq

    branch = log.fork_at(fork_seq, label=f"gauge::{variable_id}")
    branch.append(
        "perturb_variable",
        variable_id=variable_id,
        payload={"value": proxy_value},
        source="gauge_fixing_probe",
    )

    base_commit = commit_fn(log.project())
    alt_commit = commit_fn(branch.project())
    return GaugeProbeResult(
        variable_id=variable_id,
        proxy_value=proxy_value,
        fork_seq=fork_seq,
        commitment_changed=base_commit != alt_commit,
        base_commitment=base_commit,
        alt_commitment=alt_commit,
    )
