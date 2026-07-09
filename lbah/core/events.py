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
* **Gauge-fixing** becomes a real intervention — :func:`gauge_fixing_probe`
  substitutes a gauge-equivalent value for a concern variable *everywhere it
  appears in the input the agent reads* (the ledger node and the task metadata
  the ledger embeds), then diffs the resulting commitment. Perturbing a single
  carrier would miss agents that read the same distinction from another carrier;
  the value-sweep perturbs the distinction, not one node. The verdict is scoped
  by whether the value was present at all, so out-of-ledger provenance is not
  mistaken for a proxy (see :class:`GaugeProbeResult`).
* **Reopenability** becomes a freshness event over a temporal log rather than
  an in-place field poke.

The models are pure and deterministic: projection is seq-ordered and never
consults wall-clock time. ``ts`` is optional provenance metadata and plays no
part in the fold, so replays are reproducible.
"""

from __future__ import annotations

from typing import Any, Callable, Literal

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
    "record_llm_io",     # PoE-style envelope of one model .complete() request/response
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

            if event.type in {"note", "record_llm_io"}:
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


GaugeVerdict = Literal[
    "gauge_fixed",                 # commitment moved when the distinction was perturbed
    "invariant_but_value_present", # value is in the commitment but tracks no swept carrier
    "invariant_and_absent",        # value neither moves the commitment nor appears in it
]


class GaugeProbeResult(BaseModel):
    """Outcome of a counterfactual gauge-fixing probe.

    The verdict is deliberately three-way, not pass/fail, because a gauge
    failure is only damning *relative to transport* (is the value present in
    the commitment at all?):

    * ``gauge_fixed`` — perturbing the distinction moved the commitment. The
      variable is load-bearing. **Pass.**
    * ``invariant_but_value_present`` — the value appears in the commitment but
      is invariant to perturbing every ledger/task carrier. Its provenance is
      outside the swept bundle (an external tool, the agent's own memory, or a
      hardcoded constant). Ambiguous, so it does **not** block — but it is
      flagged and lightly dinged, because it cannot be verified as load-bearing.
    * ``invariant_and_absent`` — the value neither moves the commitment nor
      appears in it. A clean proxy: `decodability-is-not-load`. **Block.**
    """

    variable_id: str
    proxy_value: Any | None
    verdict: GaugeVerdict
    commitment_changed: bool
    value_present: bool = False
    base_commitment: Any | None = None
    alt_commitment: Any | None = None

    def as_gate_result(self) -> GateResult:
        if self.verdict == "gauge_fixed":
            passed, score, reason = (
                True,
                1.0,
                f"commitment moved when {self.variable_id} was perturbed across "
                "all carriers — gauge fixed",
            )
        elif self.verdict == "invariant_but_value_present":
            passed, score, reason = (
                True,
                0.75,
                f"{self.variable_id}'s value is present in the commitment but "
                "invariant to perturbing every ledger/task carrier — provenance "
                "is outside the swept bundle (external tool, memory, or hardcoded); "
                "not verifiable as load-bearing here",
            )
        else:  # invariant_and_absent
            passed, score, reason = (
                False,
                0.0,
                f"commitment invariant to {self.variable_id} and its value is "
                "absent — distinction is not load-bearing (decodability-is-not-load)",
            )
        return GateResult(
            gate_name="proxy::gauge_fixing",
            gate_kind="proxy",
            passed=passed,
            score=score,
            reason=reason,
            evidence={
                "variable_id": self.variable_id,
                "proxy_value": self.proxy_value,
                "verdict": self.verdict,
                "value_present": self.value_present,
            },
            concern_id=self.variable_id,
            weight=1.0,
        )


def _sweep_value(obj: Any, old: Any, new: Any) -> Any:
    """Return a copy of ``obj`` with every leaf equal to ``old`` replaced by ``new``.

    Type-strict equality avoids ``1 == True`` style collisions. Only whole-leaf
    matches are replaced (never substrings), so a value appearing inside a
    longer string is left alone.
    """
    if isinstance(obj, dict):
        return {k: _sweep_value(v, old, new) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sweep_value(v, old, new) for v in obj]
    if type(obj) is type(old) and obj == old:
        return new
    return obj


def _leaf_values(obj: Any) -> list[Any]:
    out: list[Any] = []

    def walk(v: Any) -> None:
        if isinstance(v, dict):
            for x in v.values():
                walk(x)
        elif isinstance(v, (list, tuple)):
            for x in v:
                walk(x)
        else:
            out.append(v)

    walk(obj)
    return out


def _value_present(old: Any, commitment: Any) -> bool:
    return any(type(l) is type(old) and l == old for l in _leaf_values(commitment))


def gauge_fixing_probe(
    log: ConcernEventLog,
    variable_id: str,
    proxy_value: Any,
    commit_fn: Callable[[ConcernLedger], Any],
) -> GaugeProbeResult:
    """Run a gauge-fixing intervention on ``variable_id``.

    ``commit_fn`` maps a ledger projection to the commitment the system would
    make from it (in real use, the agent proposing an action; in tests, any
    deterministic function). The probe:

    1. projects the log to the working ledger,
    2. builds an alternate projection where the variable's value ``v`` is
       replaced by ``proxy_value`` **everywhere it appears** in the ledger
       bundle — including the task metadata the ledger embeds — so an agent that
       reads the distinction from any of those carriers sees the swap,
    3. compares ``commit_fn`` on the two projections.

    The probe intervenes on the *distinction*, not on a single carrier of it.
    A single-node perturbation would falsely mark an agent that sources the
    value from task metadata (rather than the ledger node) as not-load-bearing.

    Note: the sweep reaches carriers embedded in the ledger/task. It does not
    reach ``State.scratch`` or values the agent derives outside its input; those
    surface as ``invariant_but_value_present`` rather than a false block.
    """
    ledger = log.project()
    var = ledger.by_id(variable_id)
    if var is None:
        raise KeyError(f"variable {variable_id!r} is not present in the ledger projection")

    old = var.value
    base_ledger = ledger
    if old is None:
        # No value to sweep — override just the node so the probe still runs.
        dump = ledger.model_dump()
        for entry in dump.get("variables", []):
            if entry.get("id") == variable_id:
                entry["value"] = proxy_value
        alt_ledger = ConcernLedger.model_validate(dump)
    else:
        alt_ledger = ConcernLedger.model_validate(
            _sweep_value(ledger.model_dump(), old, proxy_value)
        )

    base_commit = commit_fn(base_ledger)
    alt_commit = commit_fn(alt_ledger)
    changed = base_commit != alt_commit
    present = _value_present(old, base_commit) if old is not None else False

    if changed:
        verdict: GaugeVerdict = "gauge_fixed"
    elif present:
        verdict = "invariant_but_value_present"
    else:
        verdict = "invariant_and_absent"

    return GaugeProbeResult(
        variable_id=variable_id,
        proxy_value=proxy_value,
        verdict=verdict,
        commitment_changed=changed,
        value_present=present,
        base_commitment=base_commit,
        alt_commitment=alt_commit,
    )
