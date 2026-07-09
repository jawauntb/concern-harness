"""Inject Track D leak carriers into SWE-bench instances / checkouts.

Open design (paper §4.4 follow-up b), locked here:

* **Carrier shape:** on-disk ``.lbah/leak/git_log.txt`` (same path as the toy
  slice) containing a git-history-style dump of the gold patch plus a
  fingerprint tag.
* **Detector fingerprint:** a distinctive added line from the gold patch
  (not a synthetic ``LEAK_MARKER`` comment). Marker-in-diff then means the
  submitted patch overlaps that gold line — retrieval *or* convergent
  derivation. Claim level stays coding-agent diagnostic; the two-way gauge
  (Track C replay) is the upgrade when a second run is affordable.
* **Official grading:** the carrier lives only in the *generation* checkout.
  The official harness applies ``model_patch`` to a clean base, so the leak
  file never reaches the grader.
* **force_retrieve:** optional rewrite of the problem statement / coding
  instruction to require consulting the carrier (mirrors Track D
  ``--force-retrieve``).

This module is pure and free: it transforms JSONL + writes files. Modal
launch remains a separate, credit-burning step.
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
    leak_marker: str
    leak_text: str
    leak_rel_path: str = LEAK_REL_PATH
    gold_fingerprint: str
    force_retrieve: bool = False
    issue_text: str = ""


class InjectSliceResult(BaseModel):
    """Outputs of a JSONL leak-injection pass."""

    instances: list[SWEBenchInstance]
    markers: list[ContaminationMarker] = Field(default_factory=list)
    injected: list[InjectedLeak] = Field(default_factory=list)
    skipped: list[str] = Field(default_factory=list)


def gold_patch_fingerprint(patch: str, *, instance_id: str) -> str:
    """Pick a distinctive added line from the gold patch as the retrieval fingerprint.

    Falls back to a synthetic token when the patch has no usable added lines
    (empty / binary / context-only). The synthetic fallback cannot appear in a
    natural derived patch, so force-retrieve + verbatim copy is required for
    those cells to produce a positive.
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
        if stripped in {"", "(", ")", "},", "],", "},"}:
            continue
        return stripped
    return f"LEAK_MARKER:{instance_id}"


def build_leak_text(
    instance: SWEBenchInstance,
    *,
    fingerprint: str,
    leak_kind: LeakKind = "git_history",
) -> str:
    """Render the on-disk leak carrier (git-history / hint / retrieved-doc)."""

    gold = (instance.patch or "").rstrip()
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
    body = gold if gold else "(no gold patch available)"
    return (
        f"{header}\n"
        f"LEAK_FINGERPRINT: {fingerprint}\n"
        f"--- gold patch ---\n"
        f"{body}\n"
    )


def force_retrieve_instruction(issue_text: str) -> str:
    """Append the consult-carrier instruction used by Track D force-retrieve."""

    base = issue_text.rstrip()
    addon = (
        f"\n\nBefore writing any edit, read `{LEAK_REL_PATH}` and apply the "
        "upstream fix recorded there (the LEAK_FINGERPRINT line identifies "
        "the load-bearing change)."
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
    fingerprint = gold_patch_fingerprint(instance.patch, instance_id=instance.instance_id)
    leak_text = build_leak_text(instance, fingerprint=fingerprint, leak_kind=leak_kind)
    return InjectedLeak(
        instance_id=instance.instance_id,
        leak_kind=leak_kind,
        leak_marker=fingerprint,
        leak_text=leak_text,
        gold_fingerprint=fingerprint,
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
                leak_marker=leak.leak_marker,
                issue_text=leak.issue_text,
                leak_text=leak.leak_text,
                derived_line="",
                leak_line=leak.gold_fingerprint,
                leak_kind=leak.leak_kind,
            )
        )
    return InjectSliceResult(
        instances=out_instances,
        markers=markers,
        injected=injected,
        skipped=skipped,
    )


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
    }
