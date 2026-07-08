from __future__ import annotations

import json
from pathlib import Path

import pytest

from lbah.coding import (
    SWEBenchOfficialHarnessSpec,
    swebench_candidate_id,
    write_swebench_candidate_matrix,
)


def _prediction(instance_id: str, candidate_id: str) -> str:
    return json.dumps(
        {
            "instance_id": instance_id,
            "model_name_or_path": f"lbah-{candidate_id}",
            "model_patch": f"diff --git a/{instance_id}.py b/{instance_id}.py\n",
        }
    )


def _result(instance_id: str, candidate_index: int, *, returncode: int = 0) -> dict:
    candidate_id = swebench_candidate_id(candidate_index)
    return {
        "instance_id": instance_id,
        "candidate_id": candidate_id,
        "candidate_index": candidate_index,
        "returncode": returncode,
        "prediction": _prediction(instance_id, candidate_id) + "\n" if returncode == 0 else "",
        "stdout": "",
        "stderr": "",
        "run": "",
    }


def test_candidate_id_is_stable_and_orderable():
    assert [swebench_candidate_id(index) for index in range(3)] == [
        "candidate_000",
        "candidate_001",
        "candidate_002",
    ]
    with pytest.raises(ValueError):
        swebench_candidate_id(-1)


def test_write_candidate_matrix_creates_official_inputs_per_candidate(tmp_path: Path):
    instance_ids = ["repo__a-1", "repo__b-2"]
    candidate_ids = [swebench_candidate_id(0), swebench_candidate_id(1)]
    results = [
        _result(instance_id, candidate_index)
        for instance_id in instance_ids
        for candidate_index in range(2)
    ]
    spec = SWEBenchOfficialHarnessSpec(
        dataset_name="princeton-nlp/SWE-bench_Lite",
        run_id="lbah-candidates",
        max_workers=4,
        modal=True,
    )

    manifest = write_swebench_candidate_matrix(
        tmp_path,
        results,
        spec=spec,
        instance_ids=instance_ids,
        candidate_ids=candidate_ids,
        subset_sizes=[2],
    )

    assert manifest.candidate_count == 2
    assert [candidate.run_id for candidate in manifest.candidates] == [
        "lbah-candidates-candidate_000",
        "lbah-candidates-candidate_001",
    ]
    first = manifest.candidates[0]
    predictions = Path(first.predictions_path).read_text().splitlines()
    assert [json.loads(line)["instance_id"] for line in predictions] == instance_ids
    assert first.command[first.command.index("--run_id") + 1] == "lbah-candidates-candidate_000"
    assert first.command[first.command.index("--modal") + 1] == "true"
    subset_path = tmp_path / "candidates" / "candidate_000" / "official" / "subsets" / "n2.json"
    subset = json.loads(subset_path.read_text())
    assert subset["instance_ids"] == instance_ids
    assert (tmp_path / "candidate_matrix_manifest.json").exists()


def test_candidate_matrix_strict_mode_rejects_missing_predictions(tmp_path: Path):
    spec = SWEBenchOfficialHarnessSpec(run_id="lbah-candidates", modal=True)

    with pytest.raises(ValueError, match="candidate_001:repo__a-1:missing_prediction"):
        write_swebench_candidate_matrix(
            tmp_path,
            [_result("repo__a-1", 0)],
            spec=spec,
            instance_ids=["repo__a-1"],
            candidate_ids=[swebench_candidate_id(0), swebench_candidate_id(1)],
            subset_sizes=[1],
            strict=True,
        )


def test_candidate_matrix_rejects_empty_candidate_columns(tmp_path: Path):
    spec = SWEBenchOfficialHarnessSpec(run_id="lbah-candidates", modal=True)

    with pytest.raises(ValueError, match="at least one candidate"):
        write_swebench_candidate_matrix(
            tmp_path,
            [],
            spec=spec,
            instance_ids=["repo__a-1"],
            candidate_ids=[],
        )


def test_candidate_matrix_non_strict_writes_partial_candidates(tmp_path: Path):
    spec = SWEBenchOfficialHarnessSpec(run_id="lbah-candidates", modal=True)

    manifest = write_swebench_candidate_matrix(
        tmp_path,
        [_result("repo__a-1", 0), _result("repo__a-1", 1, returncode=1)],
        spec=spec,
        instance_ids=["repo__a-1"],
        candidate_ids=[swebench_candidate_id(0), swebench_candidate_id(1)],
        subset_sizes=[1],
        strict=False,
    )

    assert manifest.failed_generations == ["candidate_001:repo__a-1:returncode=1"]
    assert manifest.missing_predictions == ["candidate_001:repo__a-1:missing_prediction"]
    assert Path(manifest.candidates[1].predictions_path).read_text() == ""
