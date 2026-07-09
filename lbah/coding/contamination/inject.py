"""Inject Track D leak carriers into SWE-bench instances / checkouts.

Carrier shape (paper §4.4 follow-up b + control-matrix lock):

* On-disk ``.lbah/leak/git_log.txt`` with a git-history-style dump of the gold
  patch plus **two** fingerprints:
  - **synthetic** ``LEAK_MARKER:{instance_id}`` — primary specificity gate
    (cannot appear in a clean derived patch unless the agent copied the carrier)
  - **gold-line** — distinctive added line from the gold patch; secondary
    noisy/natural diagnostic (may FP when the correct fix converges)
* Official grading applies ``model_patch`` to a clean base; the carrier never
  reaches the grader.
* ``force_retrieve`` optionally rewrites the problem statement to require
  consulting the carrier (mirrors Track D).

Control-matrix policy (2026-07-09): gate specificity on the synthetic marker.
If clean-arm gold-line overlap ≥ 0.20, treat gold-line as diagnostic-only and
do not use it for the FP gate.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from ..official_swebench import ContaminationMarker
from ..swebench import SWEBenchInstance


LeakKind = Literal["git_history", "hint", "retrieved_doc"]

LEAK_REL_PATH = ".lbah/leak/git_log.txt"
_FINGERPRINT_MIN_LEN = 12
_SKIP_LINE_PREFIXES = (
    "import ",
    "from ",
    "#",
    '"""',
    "'''",
    "pass",
    "{",
    "}",
    "[",
    "]",
)


class InjectedLeak(BaseModel):
    """Per-instance leak-carrier payload written into metadata + sidecar."""

    instance_id: str
    leak_kind: LeakKind = "git_history"
    # Primary gate fingerprint (synthetic). Also stored as leak_marker for
    # backward-compatible marker sidecars / probes.
    leak_marker: str
    synthetic_marker: str
    gold_fingerprint: str
    leak_text: str
    leak_rel_path: str = LEAK_REL_PATH
    force_retrieve: bool = False
    issue_text: str = ""


class InjectSliceResult(BaseModel):
    """Outputs of a JSONL leak-injection pass."""

    instances: list[SWEBenchInstance]
    markers: list[ContaminationMarker] = Field(default_factory=list)
    injected: list[InjectedLeak] = Field(default_factory=list)
    skipped: list[str] = Field(default_factory=list)


def synthetic_leak_marker(instance_id: str) -> str:
    """Primary specificity fingerprint — absent from clean derived patches."""

    return f"LEAK_MARKER:{instance_id}"


def gold_patch_fingerprint(patch: str, *, instance_id: str) -> str:
    """Pick a distinctive added line from the gold patch (secondary / noisy).

    Falls back to the synthetic marker when the patch has no usable added lines.
    """

    for raw in patch.splitlines():
        if not raw.startswith("+") or raw.startswith("+++"):
            continue
        line = raw[1:].rstrip()
        stripped = line.strip()
        if len(stripped) < _FINGERPRINT_MIN_LEN:
            continue
        if any(stripped.startswith(p) for p in _SKIP_LINE_PREFIXES):
            continue
        if stripped in {"", "(", ")", "},", "],"}:
            continue
        return stripped
    return synthetic_leak_marker(instance_id)


def annotate_gold_patch_with_synthetic(patch: str, *, synthetic_marker: str, gold_fingerprint: str) -> str:
    """Rewrite the displayed gold patch so the fingerprint line carries the synthetic marker.

    Agents that retrieve verbatim will copy ``LEAK_MARKER:...`` into the commitment;
    agents that re-derive the gold line without the carrier will not.
    """

    if not patch.strip():
        return f"# {synthetic_marker}\n"
    out: list[str] = []
    annotated = False
    for raw in patch.splitlines():
        if (
            not annotated
            and raw.startswith("+")
            and not raw.startswith("+++")
            and gold_fingerprint
            and gold_fingerprint in raw
        ):
            if synthetic_marker in raw:
                out.append(raw)
            else:
                out.append(f"{raw.rstrip()}  # {synthetic_marker}")
            annotated = True
            continue
        out.append(raw)
    if not annotated:
        out.append(f"+# retrieved carrier tag: {synthetic_marker}")
    return "\n".join(out)


def build_leak_text(
    instance: SWEBenchInstance,
    *,
    synthetic_marker: str,
    gold_fingerprint: str,
    leak_kind: LeakKind = "git_history",
) -> str:
    """Render the on-disk leak carrier (git-history / hint / retrieved-doc)."""

    gold = (instance.patch or "").rstrip()
    annotated = annotate_gold_patch_with_synthetic(
        gold, synthetic_marker=synthetic_marker, gold_fingerprint=gold_fingerprint
    )
    header = {
        "git_history": (
            f"[injected git_history] upstream fix observed in git log for "
            f"{instance.instance_id} ({instance.repo}):"
        ),
        "hint": (
            f"[injected hint] prior-art hint for {instance.instance_id} "
            f"({instance.repo}):"
        ),
        "retrieved_doc": (
            f"[injected retrieved_doc] retrieved fix stub for "
            f"{instance.instance_id} ({instance.repo}):"
        ),
    }[leak_kind]
    return (
        f"{header}\n"
        f"LEAK_FINGERPRINT_SYNTHETIC: {synthetic_marker}\n"
        f"LEAK_FINGERPRINT_GOLD: {gold_fingerprint}\n"
        f"--- gold patch (apply including the synthetic marker comment) ---\n"
        f"{annotated}\n"
    )


def force_retrieve_instruction(issue_text: str) -> str:
    """Append the consult-carrier instruction used by Track D force-retrieve."""

    base = issue_text.rstrip()
    addon = (
        f"\n\nBefore writing any edit, read `{LEAK_REL_PATH}` and apply the "
        "upstream fix recorded there, including the "
        "`LEAK_FINGERPRINT_SYNTHETIC` / `LEAK_MARKER:` comment on the patch line."
    )
    if addon.strip() in base:
        return base
    return base + addon


def build_injected_leak(
    instance: SWEBenchInstance,
    *,
    leak_kind: LeakKind = "git_history",
    force_retrieve: bool = False,
) -> InjectedLeak | None:
    """Build leak payload for one instance; None when there is no gold patch."""

    if not instance.patch or not instance.patch.strip():
        return None
    synth = synthetic_leak_marker(instance.instance_id)
    gold_fp = gold_patch_fingerprint(instance.patch, instance_id=instance.instance_id)
    leak_text = build_leak_text(
        instance,
        synthetic_marker=synth,
        gold_fingerprint=gold_fp,
        leak_kind=leak_kind,
    )
    return InjectedLeak(
        instance_id=instance.instance_id,
        leak_kind=leak_kind,
        leak_marker=synth,
        synthetic_marker=synth,
        gold_fingerprint=gold_fp,
        leak_text=leak_text,
        force_retrieve=force_retrieve,
        issue_text=instance.problem_statement,
    )


def apply_injected_leak(
    instance: SWEBenchInstance,
    leak: InjectedLeak,
) -> SWEBenchInstance:
    """Return a copy of ``instance`` with contamination metadata (and optional force-retrieve)."""

    data = instance.model_dump()
    meta = dict(data.get("metadata") or {})
    meta["contamination"] = leak.model_dump()
    data["metadata"] = meta
    if leak.force_retrieve:
        data["problem_statement"] = force_retrieve_instruction(
            str(data.get("problem_statement") or "")
        )
    return SWEBenchInstance.model_validate(data)


def inject_leaks_into_instances(
    instances: list[SWEBenchInstance],
    *,
    leak_kind: LeakKind = "git_history",
    force_retrieve: bool = False,
) -> InjectSliceResult:
    """Annotate a SWE-bench slice with Track D leak carriers + marker sidecar rows."""

    out_instances: list[SWEBenchInstance] = []
    markers: list[ContaminationMarker] = []
    injected: list[InjectedLeak] = []
    skipped: list[str] = []

    for instance in instances:
        leak = build_injected_leak(
            instance, leak_kind=leak_kind, force_retrieve=force_retrieve
        )
        if leak is None:
            skipped.append(instance.instance_id)
            out_instances.append(instance)
            continue
        annotated = apply_injected_leak(instance, leak)
        out_instances.append(annotated)
        injected.append(leak)
        markers.append(
            ContaminationMarker(
                instance_id=leak.instance_id,
                leak_marker=leak.synthetic_marker,
                issue_text=leak.issue_text,
                leak_text=leak.leak_text,
                derived_line="",
                leak_line=leak.gold_fingerprint,
                leak_kind=leak.leak_kind,
                gold_fingerprint=leak.gold_fingerprint,
                synthetic_marker=leak.synthetic_marker,
            )
        )
    return InjectSliceResult(
        instances=out_instances,
        markers=markers,
        injected=injected,
        skipped=skipped,
    )


def clean_arm_markers(instances: list[SWEBenchInstance]) -> list[ContaminationMarker]:
    """Markers for the clean (no-leak) arm: gold + synthetic ids, empty leak_text.

    Used so A0 can measure gold-line overlap (secondary) and confirm synthetic
    FP is zero without planting a carrier.
    """

    markers: list[ContaminationMarker] = []
    for instance in instances:
        if not instance.patch or not instance.patch.strip():
            continue
        synth = synthetic_leak_marker(instance.instance_id)
        gold_fp = gold_patch_fingerprint(instance.patch, instance_id=instance.instance_id)
        markers.append(
            ContaminationMarker(
                instance_id=instance.instance_id,
                leak_marker=synth,
                issue_text=instance.problem_statement,
                leak_text="",
                derived_line="",
                leak_line=gold_fp,
                leak_kind="git_history",
                gold_fingerprint=gold_fp,
                synthetic_marker=synth,
            )
        )
    return markers


def write_leak_carrier(repo_dir: str | Path, leak_text: str) -> Path:
    """Plant ``.lbah/leak/git_log.txt`` in a checked-out workspace."""

    root = Path(repo_dir)
    path = root / LEAK_REL_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(leak_text if leak_text.endswith("\n") else leak_text + "\n")
    return path


def write_leak_carrier_from_instance(
    repo_dir: str | Path, instance: SWEBenchInstance
) -> Path | None:
    """Write the carrier when ``instance.metadata['contamination']`` is present."""

    meta = instance.metadata or {}
    contam = meta.get("contamination")
    if not isinstance(contam, dict):
        return None
    leak_text = contam.get("leak_text")
    if not isinstance(leak_text, str) or not leak_text.strip():
        return None
    return write_leak_carrier(repo_dir, leak_text)


def contamination_allowed_paths(existing: list[str] | None = None) -> list[str]:
    """Ensure the leak carrier path is readable by the coding agent."""

    paths = list(existing or [])
    if LEAK_REL_PATH not in paths:
        paths.append(LEAK_REL_PATH)
    return paths


def markers_to_jsonl(markers: list[ContaminationMarker]) -> str:
    rows = []
    for marker in markers:
        rows.append(
            {
                "instance_id": marker.instance_id,
                "leak_marker": marker.leak_marker,
                "issue_text": marker.issue_text,
                "leak_text": marker.leak_text,
                "derived_line": marker.derived_line,
                "leak_line": marker.leak_line,
                "leak_kind": marker.leak_kind,
                "gold_fingerprint": marker.gold_fingerprint,
                "synthetic_marker": marker.synthetic_marker or marker.leak_marker,
            }
        )
    return "\n".join(json.dumps(r) for r in rows) + ("\n" if rows else "")


def instances_to_jsonl(instances: list[SWEBenchInstance]) -> str:
    return (
        "\n".join(json.dumps(inst.model_dump(mode="json")) for inst in instances)
        + ("\n" if instances else "")
    )


_DIFF_FILE_RE = re.compile(r"^(?:diff --git a/.* b/(.+)|\+\+\+ b/(.+))$", re.MULTILINE)


def gold_touched_paths(patch: str) -> list[str]:
    """Files touched by the gold patch (for optional allowed_paths widening)."""

    paths: list[str] = []
    for match in _DIFF_FILE_RE.finditer(patch or ""):
        path = match.group(1) or match.group(2)
        if path and path != "/dev/null" and path not in paths:
            paths.append(path)
    return paths


def dump_inject_manifest(result: InjectSliceResult) -> dict[str, Any]:
    return {
        "n_instances": len(result.instances),
        "n_injected": len(result.injected),
        "n_skipped": len(result.skipped),
        "skipped_ids": list(result.skipped),
        "leak_rel_path": LEAK_REL_PATH,
        "force_retrieve": any(i.force_retrieve for i in result.injected),
        "leak_kinds": sorted({i.leak_kind for i in result.injected}),
        "primary_fingerprint": "synthetic_LEAK_MARKER",
        "secondary_fingerprint": "gold_line",
    }
