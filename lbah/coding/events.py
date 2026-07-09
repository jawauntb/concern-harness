"""Event-sourced coding ledger.

Mirrors ``lbah.core.events`` for the coding stack: an append-only
:class:`CodingEventLog` whose deterministic projection is a
:class:`~lbah.coding.ledger.CodingLedger`. Mutations become events;
``lineage`` / ``fork_at`` / ``diff`` support certificates and tournaments.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .ledger import CodingConcern, CodingLedger


CodingEventType = Literal[
    "declare_concern",
    "revise_concern",
    "set_status",
    "add_evidence",
    "record_action",
    "record_observation",
    "fork_workspace",
    "note",
    "record_llm_io",
    "record_tool_io",
]


class CodingEvent(BaseModel):
    """A single append-only change to coding concern state."""

    seq: int
    type: CodingEventType
    concern_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    source: str = ""
    ts: float | None = None


class CodingConcernDelta(BaseModel):
    concern_id: str
    field: str
    before: Any | None = None
    after: Any | None = None


class CodingLedgerDiff(BaseModel):
    added_concerns: list[str] = Field(default_factory=list)
    removed_concerns: list[str] = Field(default_factory=list)
    changed: list[CodingConcernDelta] = Field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not (self.added_concerns or self.removed_concerns or self.changed)


_DIFFED_FIELDS = ("kind", "text", "concern", "status", "evidence")


class CodingEventLog(BaseModel):
    """Append-only log of coding events; the ledger is its projection."""

    model_config = ConfigDict(extra="allow")

    task_id: str
    instruction: str = ""
    events: list[CodingEvent] = Field(default_factory=list)
    forked_from: str | None = None
    fork_seq: int | None = None
    label: str = "root"

    def _next_seq(self) -> int:
        return (max((e.seq for e in self.events), default=0)) + 1

    def append(
        self,
        type: CodingEventType,
        *,
        concern_id: str | None = None,
        payload: dict[str, Any] | None = None,
        source: str = "",
        ts: float | None = None,
    ) -> CodingEvent:
        event = CodingEvent(
            seq=self._next_seq(),
            type=type,
            concern_id=concern_id,
            payload=dict(payload or {}),
            source=source,
            ts=ts,
        )
        self.events.append(event)
        return event

    def project(self) -> CodingLedger:
        """Fold events into a :class:`CodingLedger` (seq order, LWW per field)."""
        concerns: dict[str, CodingConcern] = {}
        order: list[str] = []
        observation_trail: list[dict[str, Any]] = []

        for event in sorted(self.events, key=lambda e: e.seq):
            if event.type in {
                "note",
                "record_action",
                "fork_workspace",
                "record_llm_io",
                "record_tool_io",
            }:
                continue
            if event.type == "record_observation":
                observation_trail.append(dict(event.payload))
                continue

            cid = event.concern_id or event.payload.get("id")
            if cid is None:
                continue

            if event.type == "add_evidence":
                if cid not in concerns:
                    continue
                evidence = list(concerns[cid].evidence)
                for item in event.payload.get("evidence", []) or []:
                    if item not in evidence:
                        evidence.append(item)
                concerns[cid] = concerns[cid].model_copy(update={"evidence": evidence})
                continue

            if event.type == "set_status":
                if cid not in concerns:
                    continue
                update = {k: v for k, v in event.payload.items() if k in {"status"}}
                if "evidence_item" in event.payload:
                    evidence = list(concerns[cid].evidence)
                    item = event.payload["evidence_item"]
                    if item not in evidence:
                        evidence.append(item)
                    update["evidence"] = evidence
                concerns[cid] = concerns[cid].model_copy(update=update)
                continue

            # declare_concern / revise_concern (and unknown-id creates)
            fields = {k: v for k, v in event.payload.items() if k != "id"}
            if cid in concerns:
                if "evidence" in fields and concerns[cid].evidence:
                    merged = list(
                        dict.fromkeys(list(concerns[cid].evidence) + list(fields["evidence"] or []))
                    )
                    fields = {**fields, "evidence": merged}
                concerns[cid] = concerns[cid].model_copy(update=fields)
            else:
                concerns[cid] = CodingConcern(id=cid, **fields)
                order.append(cid)

        return CodingLedger(
            task_id=self.task_id,
            instruction=self.instruction,
            concerns=[concerns[c] for c in order],
            events=observation_trail,
        )

    def lineage(self, concern_id: str) -> list[CodingEvent]:
        return [
            e
            for e in sorted(self.events, key=lambda e: e.seq)
            if e.concern_id == concern_id
        ]

    def fork_at(self, seq: int, *, label: str | None = None) -> "CodingEventLog":
        kept = [e.model_copy(deep=True) for e in self.events if e.seq <= seq]
        return CodingEventLog(
            task_id=self.task_id,
            instruction=self.instruction,
            events=kept,
            forked_from=self.label,
            fork_seq=seq,
            label=label or f"{self.label}@{seq}",
        )

    def diff(self, other: "CodingEventLog") -> CodingLedgerDiff:
        before = {c.id: c for c in self.project().concerns}
        after = {c.id: c for c in other.project().concerns}
        added = [cid for cid in after if cid not in before]
        removed = [cid for cid in before if cid not in after]
        changed: list[CodingConcernDelta] = []
        for cid in before:
            if cid not in after:
                continue
            b, a = before[cid], after[cid]
            for field in _DIFFED_FIELDS:
                bv, av = getattr(b, field), getattr(a, field)
                if bv != av:
                    changed.append(
                        CodingConcernDelta(concern_id=cid, field=field, before=bv, after=av)
                    )
        return CodingLedgerDiff(
            added_concerns=sorted(added),
            removed_concerns=sorted(removed),
            changed=changed,
        )


def events_from_ledger(ledger: CodingLedger) -> CodingEventLog:
    """Bootstrap an event log whose projection matches ``ledger`` concerns."""
    log = CodingEventLog(task_id=ledger.task_id, instruction=ledger.instruction)
    for concern in ledger.concerns:
        log.append(
            "declare_concern",
            concern_id=concern.id,
            payload=concern.model_dump(),
            source="ledger",
        )
    for observation in ledger.events:
        log.append(
            "record_observation",
            payload=dict(observation),
            source="ledger.events",
        )
    return log
