"""Operational helpers for replaying LBAH patches with the official SWE-bench harness."""

from __future__ import annotations

import json
import platform
import shlex
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Optional


OfficialSWEBenchTarget = Literal["local", "modal"]


@dataclass(frozen=True)
class OfficialSWEBenchRunPlan:
    command: list[str]
    wrapped_command: list[str]
    warnings: list[str]

    def shell_command(self) -> str:
        return " ".join(shlex.quote(part) for part in self.wrapped_command)


@dataclass(frozen=True)
class DopplerRunConfig:
    project: str = "cofounder"
    config: str = "dev"

    def prefix(self) -> list[str]:
        return [
            "doppler",
            "run",
            "--project",
            self.project,
            "--config",
            self.config,
            "--",
        ]


def load_official_swebench_command(path: str | Path) -> list[str]:
    """Load a command from run_evaluation_command.json or a subset manifest."""

    payload = json.loads(Path(path).read_text())
    if isinstance(payload, dict):
        if isinstance(payload.get("command"), list):
            return [str(part) for part in payload["command"]]
        if isinstance(payload.get("official_command"), list):
            return [str(part) for part in payload["official_command"]]
    if isinstance(payload, list):
        return [str(part) for part in payload]
    raise ValueError(f"{path} does not contain an official SWE-bench command")


def plan_official_swebench_run(
    command: list[str],
    *,
    target: OfficialSWEBenchTarget = "modal",
    max_workers: int | None = None,
    run_id: str | None = None,
    cache_level: str | None = None,
    namespace: str | None = None,
    modal_gpu: str | None = None,
    use_doppler: bool = False,
    doppler: DopplerRunConfig | None = None,
    allow_local_low_disk: bool = False,
) -> OfficialSWEBenchRunPlan:
    """Prepare a local or Modal official-harness command without executing it."""

    planned = list(command)
    warnings = _environment_warnings(target)
    if target == "modal":
        planned = _set_option(planned, "--modal", "true")
        if modal_gpu:
            warnings.append(
                "official SWE-bench Modal grading does not expose GPU selection; "
                f"requested {modal_gpu!r} is ignored by the upstream runner"
            )
    elif platform.machine().lower() in {"arm64", "aarch64"} and namespace is None:
        namespace = ""

    if max_workers is not None:
        planned = _set_option(planned, "--max_workers", str(max_workers))
    if run_id:
        planned = _set_option(planned, "--run_id", run_id)
    if cache_level:
        planned = _set_option(planned, "--cache_level", cache_level)
    if namespace is not None:
        planned = _set_option(planned, "--namespace", namespace)

    if target == "local":
        free_gb = shutil.disk_usage(Path.cwd()).free / (1024**3)
        if free_gb < 100 and not allow_local_low_disk:
            warnings.append(
                f"local disk has only {free_gb:.1f}GB free; official SWE-bench docs recommend about 120GB"
            )

    wrapped = list(planned)
    if use_doppler:
        wrapped = (doppler or DopplerRunConfig()).prefix() + wrapped
    return OfficialSWEBenchRunPlan(command=planned, wrapped_command=wrapped, warnings=warnings)


def run_official_swebench_plan(plan: OfficialSWEBenchRunPlan) -> subprocess.CompletedProcess[str]:
    return subprocess.run(plan.wrapped_command, text=True, check=False)


def _environment_warnings(target: OfficialSWEBenchTarget) -> list[str]:
    warnings: list[str] = []
    if target == "local" and shutil.which("docker") is None:
        warnings.append("docker is not on PATH")
    if target == "modal":
        if shutil.which("doppler") is None:
            warnings.append("doppler is not on PATH; use env vars or run modal setup first")
        warnings.append(
            "official SWE-bench Modal grading parallelizes with --max_workers but its sandbox runtime is CPU-bound; "
            "use L4s for Modal-based patch generation, not this official grader"
        )
    return warnings


@dataclass(frozen=True)
class ContaminationMarker:
    """Contamination-slice metadata for one SWE-bench instance.

    A Modal SWE-bench run does not carry Track D leak carriers by itself; a
    caller who wants a retroactive contamination probe must supply per-instance
    ``leak_marker`` / ``issue_text`` metadata (typically from an eval-time
    sidecar file).

    Dual fingerprints (control-matrix lock):
    * ``leak_marker`` / ``synthetic_marker`` — primary specificity gate
    * ``gold_fingerprint`` / ``leak_line`` — secondary noisy/natural diagnostic
    """

    instance_id: str
    leak_marker: str
    issue_text: str = ""
    leak_text: str = ""
    derived_line: str = ""
    leak_line: str = ""
    leak_kind: str = "git_history"
    gold_fingerprint: str = ""
    synthetic_marker: str = ""


@dataclass(frozen=True)
class ContaminationProbeArtifact:
    """One retroactive contamination-probe result for a Modal artifact row."""

    instance_id: str
    resolved: bool
    flagged: bool
    leak_marker_in_diff: bool
    reason: str
    gold_fingerprint_in_diff: bool = False
    synthetic_marker_in_diff: bool = False


@dataclass(frozen=True)
class ContaminationProbePlan:
    """Plan for retroactively probing Modal-graded artifacts."""

    artifact_dir: Path
    predictions_path: Path
    report_path: Optional[Path]
    markers_path: Optional[Path]
    resolved_ids: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _load_predictions(predictions_path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in predictions_path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        rows.append(json.loads(line))
    return rows


def _load_markers(markers_path: Path) -> dict[str, ContaminationMarker]:
    """Read a JSONL sidecar mapping ``instance_id`` -> Track D metadata."""

    markers: dict[str, ContaminationMarker] = {}
    for line in markers_path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        payload = json.loads(line)
        leak_marker = str(payload["leak_marker"])
        synth = str(payload.get("synthetic_marker") or leak_marker)
        gold = str(payload.get("gold_fingerprint") or payload.get("leak_line") or "")
        marker = ContaminationMarker(
            instance_id=str(payload["instance_id"]),
            leak_marker=leak_marker,
            issue_text=str(payload.get("issue_text", "")),
            leak_text=str(payload.get("leak_text", "")),
            derived_line=str(payload.get("derived_line", "")),
            leak_line=str(payload.get("leak_line") or gold),
            leak_kind=str(payload.get("leak_kind", "git_history")),
            gold_fingerprint=gold,
            synthetic_marker=synth,
        )
        markers[marker.instance_id] = marker
    return markers


def _find_report(artifact_dir: Path) -> Optional[Path]:
    """Locate the official SWE-bench report JSON inside a Modal artifact dir."""

    for candidate in artifact_dir.glob("*.json"):
        try:
            payload = json.loads(candidate.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        if isinstance(payload, dict) and "resolved_ids" in payload:
            return candidate
    return None


def plan_contamination_probe_on_artifacts(
    artifact_dir: str | Path,
    *,
    predictions_path: str | Path | None = None,
    report_path: str | Path | None = None,
    markers_path: str | Path | None = None,
) -> ContaminationProbePlan:
    """Locate the predictions + report + marker sidecar under a Modal artifact dir.

    This is deliberately I/O-only: it neither invokes Modal nor runs the probe.
    Callers use :func:`run_contamination_probe_on_artifacts` (Stage 2) or drive
    the plan themselves; the scaffold path is tested against a mocked artifact
    directory.
    """

    artifact_dir = Path(artifact_dir)
    warnings: list[str] = []
    predictions = Path(predictions_path) if predictions_path else artifact_dir / "predictions.jsonl"
    if not predictions.exists():
        raise FileNotFoundError(f"predictions.jsonl not found under {artifact_dir}")

    report = Path(report_path) if report_path else _find_report(artifact_dir)
    if report is None:
        warnings.append(
            "no official SWE-bench report JSON found; probe will treat every "
            "prediction as resolved"
        )

    markers = Path(markers_path) if markers_path else artifact_dir / "contamination_markers.jsonl"
    if not markers.exists():
        warnings.append(
            f"contamination_markers.jsonl not found at {markers}; probe will run "
            "only on rows whose predictions carry a leak_marker field"
        )
        markers = None

    resolved_ids: list[str] = []
    if report is not None:
        try:
            payload = json.loads(report.read_text())
            if isinstance(payload, dict):
                resolved_ids = [str(x) for x in payload.get("resolved_ids", []) or []]
        except (json.JSONDecodeError, OSError) as exc:
            warnings.append(f"failed to read report {report}: {exc}")

    return ContaminationProbePlan(
        artifact_dir=artifact_dir,
        predictions_path=predictions,
        report_path=report,
        markers_path=markers,
        resolved_ids=resolved_ids,
        warnings=warnings,
    )


def run_contamination_probe_on_artifacts(
    plan: ContaminationProbePlan,
    *,
    include_unresolved: bool = False,
) -> list[ContaminationProbeArtifact]:
    """Retroactively run the real-diff contamination probe on Modal artifacts.

    Scaffold-only path: reads the predictions.jsonl + resolved report + optional
    marker sidecar assembled by :func:`plan_contamination_probe_on_artifacts`,
    then applies the marker-inspection heuristic used by the local pilot. Does
    not talk to Modal or spawn a coding harness — everything comes from files
    written by an earlier grading run.
    """

    predictions = _load_predictions(plan.predictions_path)
    resolved = set(plan.resolved_ids) if plan.report_path is not None else None
    markers: dict[str, ContaminationMarker] = {}
    if plan.markers_path is not None:
        markers = _load_markers(plan.markers_path)

    out: list[ContaminationProbeArtifact] = []
    for row in predictions:
        instance_id = str(row.get("instance_id", ""))
        patch = str(row.get("model_patch") or "")
        marker = markers.get(instance_id)
        if marker is None:
            inline = row.get("leak_marker")
            if isinstance(inline, str) and inline:
                marker = ContaminationMarker(instance_id=instance_id, leak_marker=inline)
        if marker is None:
            out.append(
                ContaminationProbeArtifact(
                    instance_id=instance_id,
                    resolved=(resolved is None) or (instance_id in resolved),
                    flagged=False,
                    leak_marker_in_diff=False,
                    reason="no contamination marker for this instance; probe skipped",
                )
            )
            continue

        synth = marker.synthetic_marker or marker.leak_marker
        gold = marker.gold_fingerprint or marker.leak_line
        synth_in = bool(synth) and synth in patch
        gold_in = bool(gold) and gold in patch
        # Primary gate = synthetic marker (specificity). leak_marker_in_diff
        # stays aliased to the primary gate for backward-compatible callers.
        marker_in_diff = synth_in

        is_resolved = (resolved is None) or (instance_id in resolved)
        if not is_resolved and not include_unresolved:
            out.append(
                ContaminationProbeArtifact(
                    instance_id=instance_id,
                    resolved=False,
                    flagged=False,
                    leak_marker_in_diff=marker_in_diff,
                    reason="skipped: instance not resolved by official grader",
                    gold_fingerprint_in_diff=gold_in,
                    synthetic_marker_in_diff=synth_in,
                )
            )
            continue

        derived_in_diff = bool(marker.derived_line) and marker.derived_line in patch
        # Retrieved-not-derived heuristic: primary synthetic marker present and
        # issue-only derived signal absent. Gold-line overlap is recorded but
        # does not drive ``flagged`` (too close to the correct fix on clean arms).
        flagged = marker_in_diff and not (derived_in_diff and not marker_in_diff)
        reason = (
            "retrieved-not-derived: synthetic leak marker in patch"
            if flagged
            else "derived-or-mixed: synthetic leak marker absent"
        )
        out.append(
            ContaminationProbeArtifact(
                instance_id=instance_id,
                resolved=is_resolved,
                flagged=flagged,
                leak_marker_in_diff=marker_in_diff,
                reason=reason,
                gold_fingerprint_in_diff=gold_in,
                synthetic_marker_in_diff=synth_in,
            )
        )
    return out


def _set_option(command: list[str], flag: str, value: str) -> list[str]:
    updated = list(command)
    if flag in updated:
        index = updated.index(flag)
        if index == len(updated) - 1:
            updated.append(value)
        else:
            updated[index + 1] = value
        return updated
    insert_at = updated.index("--instance_ids") if "--instance_ids" in updated else len(updated)
    updated[insert_at:insert_at] = [flag, value]
    return updated
