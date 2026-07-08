"""Candidate-matrix packaging for SWE-bench official replay."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterable, Literal

from pydantic import BaseModel, Field

from .swebench_eval import (
    SWEBenchOfficialHarnessSpec,
    official_swebench_command,
    write_swebench_subset_manifests,
)


class SWEBenchCandidateOfficialInput(BaseModel):
    """Official replay artifacts for one candidate column in a matrix run."""

    candidate_id: str
    predictions_path: str
    command_path: str
    command: list[str]
    instance_ids: list[str]
    run_id: str


class SWEBenchCandidateMatrixManifest(BaseModel):
    """Manifest for a multi-candidate SWE-bench generation matrix."""

    candidate_count: int
    instance_ids: list[str]
    candidates: list[SWEBenchCandidateOfficialInput] = Field(default_factory=list)
    strict: bool = True
    missing_predictions: list[str] = Field(default_factory=list)
    failed_generations: list[str] = Field(default_factory=list)


class SWEBenchOfficialCandidateReport(BaseModel):
    """Official SWE-bench grading result for one candidate column."""

    candidate_id: str
    report_path: str
    schema_version: int | None = None
    total_instances: int = 0
    submitted_instances: int = 0
    completed_instances: int = 0
    resolved_instances: int = 0
    unresolved_instances: int = 0
    empty_patch_instances: int = 0
    error_instances: int = 0
    submitted_ids: list[str] = Field(default_factory=list)
    completed_ids: list[str] = Field(default_factory=list)
    resolved_ids: list[str] = Field(default_factory=list)
    unresolved_ids: list[str] = Field(default_factory=list)
    empty_patch_ids: list[str] = Field(default_factory=list)
    error_ids: list[str] = Field(default_factory=list)
    incomplete_ids: list[str] = Field(default_factory=list)


class SWEBenchCandidateInstanceOutcome(BaseModel):
    """Per-instance post-hoc outcome across official candidate reports."""

    instance_id: str
    selected_candidate_id: str
    selected_status: Literal["resolved", "unresolved", "error", "missing"]
    resolved_candidate_ids: list[str] = Field(default_factory=list)
    unresolved_candidate_ids: list[str] = Field(default_factory=list)
    error_candidate_ids: list[str] = Field(default_factory=list)
    missing_candidate_ids: list[str] = Field(default_factory=list)


class SWEBenchCandidateSummary(BaseModel):
    """Aggregated official results for a SWE-bench candidate matrix."""

    schema_version: int = 1
    candidate_count: int
    report_count: int
    total_instances: int
    instance_ids: list[str]
    candidate_reports: list[SWEBenchOfficialCandidateReport]
    missing_report_candidate_ids: list[str] = Field(default_factory=list)
    oracle_resolved_instances: int
    oracle_unresolved_instances: int
    oracle_resolved_ids: list[str]
    oracle_unresolved_ids: list[str]
    instance_outcomes: list[SWEBenchCandidateInstanceOutcome]


def swebench_candidate_id(index: int) -> str:
    if index < 0:
        raise ValueError("candidate index must be non-negative")
    return f"candidate_{index:03d}"


def load_swebench_candidate_matrix_manifest(path: str | Path) -> SWEBenchCandidateMatrixManifest:
    """Load a candidate matrix manifest written by `write_swebench_candidate_matrix`."""

    return SWEBenchCandidateMatrixManifest.model_validate_json(Path(path).read_text())


def infer_swebench_candidate_id_from_path(path: str | Path) -> str:
    """Infer `candidate_000` style IDs from report or artifact paths."""

    match = re.search(r"candidate_\d+", str(path))
    if not match:
        raise ValueError(f"could not infer SWE-bench candidate id from {path}")
    return match.group(0)


def load_swebench_official_candidate_report(
    candidate_id: str,
    report_path: str | Path,
) -> SWEBenchOfficialCandidateReport:
    """Load one official SWE-bench report and attach its candidate ID."""

    path = Path(report_path)
    payload = json.loads(path.read_text())
    return SWEBenchOfficialCandidateReport(
        candidate_id=candidate_id,
        report_path=str(path),
        schema_version=payload.get("schema_version"),
        total_instances=int(payload.get("total_instances", 0)),
        submitted_instances=int(payload.get("submitted_instances", 0)),
        completed_instances=int(payload.get("completed_instances", 0)),
        resolved_instances=int(payload.get("resolved_instances", 0)),
        unresolved_instances=int(payload.get("unresolved_instances", 0)),
        empty_patch_instances=int(payload.get("empty_patch_instances", 0)),
        error_instances=int(payload.get("error_instances", 0)),
        submitted_ids=_string_list(payload.get("submitted_ids")),
        completed_ids=_string_list(payload.get("completed_ids")),
        resolved_ids=_string_list(payload.get("resolved_ids")),
        unresolved_ids=_string_list(payload.get("unresolved_ids")),
        empty_patch_ids=_string_list(payload.get("empty_patch_ids")),
        error_ids=_string_list(payload.get("error_ids")),
        incomplete_ids=_string_list(payload.get("incomplete_ids")),
    )


def summarize_swebench_candidate_reports(
    manifest: SWEBenchCandidateMatrixManifest,
    official_reports: Iterable[SWEBenchOfficialCandidateReport],
) -> SWEBenchCandidateSummary:
    """Summarize official results across candidate columns.

    The `oracle_*` fields are intentionally post-hoc: they measure whether
    candidate diversity exists, not whether a deployable ranker has selected the
    right patch before official grading.
    """

    report_by_candidate: dict[str, SWEBenchOfficialCandidateReport] = {}
    for report in official_reports:
        if report.candidate_id in report_by_candidate:
            raise ValueError(f"duplicate official report for {report.candidate_id}")
        report_by_candidate[report.candidate_id] = report

    candidate_ids = [candidate.candidate_id for candidate in manifest.candidates]
    unknown_reports = sorted(set(report_by_candidate) - set(candidate_ids))
    if unknown_reports:
        raise ValueError(f"official report candidates are not in manifest: {', '.join(unknown_reports)}")
    if not report_by_candidate:
        raise ValueError("at least one official candidate report is required")

    ordered_reports = [
        report_by_candidate[candidate_id]
        for candidate_id in candidate_ids
        if candidate_id in report_by_candidate
    ]
    missing_report_candidate_ids = [
        candidate_id for candidate_id in candidate_ids if candidate_id not in report_by_candidate
    ]
    oracle_resolved_ids: list[str] = []
    outcomes: list[SWEBenchCandidateInstanceOutcome] = []

    report_sets = {
        report.candidate_id: _classification_sets(report)
        for report in ordered_reports
    }
    for instance_id in manifest.instance_ids:
        resolved_ids: list[str] = []
        unresolved_ids: list[str] = []
        error_ids: list[str] = []
        missing_ids: list[str] = []
        for candidate_id in candidate_ids:
            sets = report_sets.get(candidate_id)
            if sets is None:
                missing_ids.append(candidate_id)
            elif instance_id in sets["resolved"]:
                resolved_ids.append(candidate_id)
            elif instance_id in sets["unresolved"]:
                unresolved_ids.append(candidate_id)
            elif instance_id in sets["error"]:
                error_ids.append(candidate_id)
            else:
                missing_ids.append(candidate_id)

        if resolved_ids:
            selected_candidate_id = resolved_ids[0]
            selected_status: Literal["resolved", "unresolved", "error", "missing"] = "resolved"
            oracle_resolved_ids.append(instance_id)
        elif unresolved_ids:
            selected_candidate_id = unresolved_ids[0]
            selected_status = "unresolved"
        elif error_ids:
            selected_candidate_id = error_ids[0]
            selected_status = "error"
        else:
            selected_candidate_id = candidate_ids[0] if candidate_ids else ""
            selected_status = "missing"

        outcomes.append(
            SWEBenchCandidateInstanceOutcome(
                instance_id=instance_id,
                selected_candidate_id=selected_candidate_id,
                selected_status=selected_status,
                resolved_candidate_ids=resolved_ids,
                unresolved_candidate_ids=unresolved_ids,
                error_candidate_ids=error_ids,
                missing_candidate_ids=missing_ids,
            )
        )

    oracle_resolved_set = set(oracle_resolved_ids)
    oracle_unresolved_ids = [
        instance_id for instance_id in manifest.instance_ids if instance_id not in oracle_resolved_set
    ]
    return SWEBenchCandidateSummary(
        candidate_count=manifest.candidate_count,
        report_count=len(ordered_reports),
        total_instances=len(manifest.instance_ids),
        instance_ids=manifest.instance_ids,
        candidate_reports=ordered_reports,
        missing_report_candidate_ids=missing_report_candidate_ids,
        oracle_resolved_instances=len(oracle_resolved_ids),
        oracle_unresolved_instances=len(oracle_unresolved_ids),
        oracle_resolved_ids=oracle_resolved_ids,
        oracle_unresolved_ids=oracle_unresolved_ids,
        instance_outcomes=outcomes,
    )


def write_swebench_candidate_summary(
    path: str | Path,
    summary: SWEBenchCandidateSummary,
) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(summary.model_dump_json(indent=2) + "\n")


def write_swebench_candidate_matrix(
    out_dir: str | Path,
    generation_results: Iterable[dict[str, Any]],
    *,
    spec: SWEBenchOfficialHarnessSpec,
    instance_ids: list[str],
    candidate_ids: list[str],
    subset_sizes: Iterable[int] = (5, 20, 50),
    strict: bool = True,
) -> SWEBenchCandidateMatrixManifest:
    """Write per-candidate predictions and official SWE-bench commands.

    `generation_results` should contain one generated prediction per
    `(instance_id, candidate_id)` pair. Each result's `prediction` field is the
    JSONL content emitted by `lbah code swebench --official` for that single
    instance.
    """

    if not candidate_ids:
        raise ValueError("candidate matrix requires at least one candidate")
    destination = Path(out_dir)
    destination.mkdir(parents=True, exist_ok=True)
    results = list(generation_results)
    (destination / "candidate_generation_results.json").write_text(json.dumps(results, indent=2))

    predictions_by_candidate = _group_prediction_lines(results)
    failed = _failed_generation_keys(results)
    missing = _missing_prediction_keys(predictions_by_candidate, instance_ids, candidate_ids)
    if strict and (failed or missing):
        details = ", ".join([*failed, *missing])
        raise ValueError(f"candidate matrix is incomplete: {details}")

    candidates: list[SWEBenchCandidateOfficialInput] = []
    for candidate_id in candidate_ids:
        candidate_dir = destination / "candidates" / candidate_id / "official"
        candidate_dir.mkdir(parents=True, exist_ok=True)
        ordered_ids = [
            instance_id
            for instance_id in instance_ids
            if instance_id in predictions_by_candidate.get(candidate_id, {})
        ]
        prediction_lines = [
            predictions_by_candidate[candidate_id][instance_id]
            for instance_id in ordered_ids
        ]
        predictions_path = candidate_dir / "predictions.jsonl"
        predictions_path.write_text("\n".join(prediction_lines) + ("\n" if prediction_lines else ""))
        (candidate_dir / "instance_ids.txt").write_text(
            "\n".join(ordered_ids) + ("\n" if ordered_ids else "")
        )

        candidate_spec = spec.model_copy(update={"run_id": f"{spec.run_id}-{candidate_id}"})
        command = official_swebench_command(
            candidate_spec,
            predictions_path=predictions_path,
            instance_ids=ordered_ids,
        )
        command_path = candidate_dir / "run_evaluation_command.json"
        command_path.write_text(
            json.dumps(
                {
                    "command": command,
                    "spec": candidate_spec.model_dump(),
                    "source": "SWE-bench candidate matrix official replay contract",
                    "candidate_id": candidate_id,
                },
                indent=2,
                sort_keys=True,
            )
        )
        write_swebench_subset_manifests(
            candidate_dir / "subsets",
            ordered_ids,
            sizes=subset_sizes,
            predictions_path=str(predictions_path),
            spec=candidate_spec,
        )
        candidates.append(
            SWEBenchCandidateOfficialInput(
                candidate_id=candidate_id,
                predictions_path=str(predictions_path),
                command_path=str(command_path),
                command=command,
                instance_ids=ordered_ids,
                run_id=candidate_spec.run_id,
            )
        )

    manifest = SWEBenchCandidateMatrixManifest(
        candidate_count=len(candidate_ids),
        instance_ids=instance_ids,
        candidates=candidates,
        strict=strict,
        missing_predictions=missing,
        failed_generations=failed,
    )
    (destination / "candidate_matrix_manifest.json").write_text(manifest.model_dump_json(indent=2))
    return manifest


def _group_prediction_lines(results: list[dict[str, Any]]) -> dict[str, dict[str, str]]:
    grouped: dict[str, dict[str, str]] = {}
    for result in results:
        candidate_id = _result_candidate_id(result)
        for line in _prediction_lines(result):
            row = json.loads(line)
            instance_id = str(row["instance_id"])
            grouped.setdefault(candidate_id, {})[instance_id] = json.dumps(row)
    return grouped


def _prediction_lines(result: dict[str, Any]) -> list[str]:
    raw = str(result.get("prediction") or "")
    return [line for line in raw.splitlines() if line.strip()]


def _failed_generation_keys(results: list[dict[str, Any]]) -> list[str]:
    failed: list[str] = []
    for result in results:
        candidate_id = _result_candidate_id(result)
        instance_id = str(result.get("instance_id", "unknown"))
        if int(result.get("returncode", 0)) != 0:
            failed.append(f"{candidate_id}:{instance_id}:returncode={result.get('returncode')}")
        elif not _prediction_lines(result):
            failed.append(f"{candidate_id}:{instance_id}:empty_prediction")
    return failed


def _result_candidate_id(result: dict[str, Any]) -> str:
    return str(result.get("candidate_id") or swebench_candidate_id(int(result.get("candidate_index", 0))))


def _missing_prediction_keys(
    predictions_by_candidate: dict[str, dict[str, str]],
    instance_ids: list[str],
    candidate_ids: list[str],
) -> list[str]:
    missing: list[str] = []
    for candidate_id in candidate_ids:
        predictions = predictions_by_candidate.get(candidate_id, {})
        for instance_id in instance_ids:
            if instance_id not in predictions:
                missing.append(f"{candidate_id}:{instance_id}:missing_prediction")
    return missing


def _string_list(raw: Any) -> list[str]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValueError(f"expected list field in official SWE-bench report, got {type(raw).__name__}")
    return [str(item) for item in raw]


def _classification_sets(
    report: SWEBenchOfficialCandidateReport,
) -> dict[str, set[str]]:
    return {
        "resolved": set(report.resolved_ids),
        "unresolved": set(report.unresolved_ids),
        "error": set(report.error_ids) | set(report.empty_patch_ids) | set(report.incomplete_ids),
    }
