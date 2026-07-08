"""Helpers for building and updating a ConcernLedger."""

from __future__ import annotations

from .schemas import ConcernLedger, ConcernVariable, CommitmentSurface, TaskSpec


def make_ledger(
    task: TaskSpec,
    variables: list[ConcernVariable],
    surfaces: list[CommitmentSurface],
) -> ConcernLedger:
    return ConcernLedger(task=task, variables=variables, surfaces=surfaces)


def merge_variables(
    existing: list[ConcernVariable],
    new: list[ConcernVariable],
) -> list[ConcernVariable]:
    """Merge a new set of concern variables into the existing ledger by id.

    Prefer the higher-concern entry when duplicates appear.
    """
    by_id: dict[str, ConcernVariable] = {v.id: v for v in existing}
    for v in new:
        if v.id in by_id and by_id[v.id].concern >= v.concern:
            continue
        by_id[v.id] = v
    return list(by_id.values())


def stale_variables(
    ledger: ConcernLedger,
    threshold: float = 0.5,
) -> list[ConcernVariable]:
    return [v for v in ledger.variables if v.freshness < threshold]
