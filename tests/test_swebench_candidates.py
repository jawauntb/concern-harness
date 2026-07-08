from __future__ import annotations

import json
from pathlib import Path

import pytest

from lbah.coding import (
    SWEBenchOfficialHarnessSpec,
    default_swebench_candidate_roles,
    infer_swebench_candidate_id_from_path,
    load_swebench_official_candidate_report,
    summarize_swebench_candidate_reports,
    swebench_candidate_id,
    write_swebench_candidate_summary,
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


def test_default_candidate_roles_are_stable_and_prompt_bearing():
    roles = default_swebench_candidate_roles([swebench_candidate_id(index) for index in range(4)])

    assert [role.role_id for role in roles] == [
        "minimal_patch",
        "test_contract",
        "root_cause",
        "edge_case",
    ]
    assert roles[0].candidate_id == "candidate_000"
    assert roles[1].role_label == "Test-contract repair"
    assert "test" in roles[1].prompt_note.lower()


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
    assert [role.role_id for role in manifest.candidate_roles] == [
        "minimal_patch",
        "test_contract",
    ]
    assert [candidate.run_id for candidate in manifest.candidates] == [
        "lbah-candidates-candidate_000",
        "lbah-candidates-candidate_001",
    ]
    first = manifest.candidates[0]
    assert first.role_id == "minimal_patch"
    assert first.role_label == "Minimal patch"
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


def test_candidate_report_summary_tracks_oracle_union(tmp_path: Path):
    instance_ids = ["repo__a-1", "repo__b-2", "repo__c-3"]
    candidate_ids = [swebench_candidate_id(0), swebench_candidate_id(1)]
    spec = SWEBenchOfficialHarnessSpec(run_id="lbah-candidates", modal=True)
    manifest = write_swebench_candidate_matrix(
        tmp_path,
        [
            _result(instance_id, candidate_index)
            for instance_id in instance_ids
            for candidate_index in range(2)
        ],
        spec=spec,
        instance_ids=instance_ids,
        candidate_ids=candidate_ids,
        subset_sizes=[3],
    )
    first_report_path = _official_report(
        tmp_path / "candidate_000_report.json",
        submitted=instance_ids,
        resolved=["repo__a-1"],
        unresolved=["repo__b-2"],
        errors=["repo__c-3"],
    )
    second_report_path = _official_report(
        tmp_path / "candidate_001_report.json",
        submitted=instance_ids,
        resolved=["repo__b-2"],
        unresolved=["repo__a-1", "repo__c-3"],
    )

    summary = summarize_swebench_candidate_reports(
        manifest,
        [
            load_swebench_official_candidate_report("candidate_000", first_report_path),
            load_swebench_official_candidate_report("candidate_001", second_report_path),
        ],
    )

    assert summary.report_count == 2
    assert summary.candidate_reports[0].role_id == "minimal_patch"
    assert summary.candidate_reports[1].role_id == "test_contract"
    assert summary.oracle_resolved_instances == 2
    assert summary.oracle_resolved_ids == ["repo__a-1", "repo__b-2"]
    assert summary.oracle_unresolved_ids == ["repo__c-3"]
    assert summary.instance_outcomes[0].selected_candidate_id == "candidate_000"
    assert summary.instance_outcomes[1].selected_candidate_id == "candidate_001"
    assert summary.instance_outcomes[2].selected_status == "unresolved"


def test_candidate_report_summary_records_missing_report(tmp_path: Path):
    spec = SWEBenchOfficialHarnessSpec(run_id="lbah-candidates", modal=True)
    manifest = write_swebench_candidate_matrix(
        tmp_path,
        [_result("repo__a-1", 0), _result("repo__a-1", 1)],
        spec=spec,
        instance_ids=["repo__a-1"],
        candidate_ids=[swebench_candidate_id(0), swebench_candidate_id(1)],
        subset_sizes=[1],
    )
    report_path = _official_report(
        tmp_path / "candidate_000_report.json",
        submitted=["repo__a-1"],
        resolved=[],
        unresolved=["repo__a-1"],
    )

    summary = summarize_swebench_candidate_reports(
        manifest,
        [load_swebench_official_candidate_report("candidate_000", report_path)],
    )

    assert summary.missing_report_candidate_ids == ["candidate_001"]
    assert summary.instance_outcomes[0].missing_candidate_ids == ["candidate_001"]
    out = tmp_path / "summary.json"
    write_swebench_candidate_summary(out, summary)
    assert json.loads(out.read_text())["oracle_unresolved_instances"] == 1


def test_candidate_id_inference_uses_report_path():
    assert (
        infer_swebench_candidate_id_from_path("runs/candidates/candidate_042/official/report.json")
        == "candidate_042"
    )
    with pytest.raises(ValueError, match="could not infer"):
        infer_swebench_candidate_id_from_path("runs/no-candidate/report.json")


def _official_report(
    path: Path,
    *,
    submitted: list[str],
    resolved: list[str],
    unresolved: list[str],
    errors: list[str] | None = None,
) -> Path:
    errors = errors or []
    path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "total_instances": len(submitted),
                "submitted_instances": len(submitted),
                "completed_instances": len(submitted),
                "resolved_instances": len(resolved),
                "unresolved_instances": len(unresolved),
                "empty_patch_instances": 0,
                "error_instances": len(errors),
                "submitted_ids": submitted,
                "completed_ids": submitted,
                "resolved_ids": resolved,
                "unresolved_ids": unresolved,
                "empty_patch_ids": [],
                "error_ids": errors,
                "incomplete_ids": [],
            }
        )
    )
    return path
