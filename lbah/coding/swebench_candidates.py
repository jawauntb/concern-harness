"""Candidate-matrix packaging for SWE-bench official replay."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

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


def swebench_candidate_id(index: int) -> str:
    if index < 0:
        raise ValueError("candidate index must be non-negative")
    return f"candidate_{index:03d}"


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
