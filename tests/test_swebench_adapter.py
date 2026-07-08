from __future__ import annotations

import json
from pathlib import Path

from lbah.coding import (
    CodingRunResult,
    SWEBenchInstance,
    infer_swebench_allowed_paths,
    load_swebench_instances,
    swebench_run_artifact,
    swebench_test_command,
    swebench_to_coding_task,
    write_swebench_run_artifact,
)


def _raw_instance() -> dict:
    return {
        "instance_id": "repo__project-123",
        "repo": "repo/project",
        "base_commit": "abc123",
        "problem_statement": "Fix the edge case in parse_item.",
        "patch": (
            "diff --git a/pkg/parser.py b/pkg/parser.py\n"
            "--- a/pkg/parser.py\n"
            "+++ b/pkg/parser.py\n"
            "@@\n"
            "-return None\n"
            "+return item\n"
        ),
        "FAIL_TO_PASS": json.dumps(["tests/test_parser.py::test_edge"]),
        "PASS_TO_PASS": ["tests/test_parser.py::test_existing"],
    }


def test_swebench_instance_normalizes_fields_and_builds_task():
    instance = SWEBenchInstance.from_mapping(_raw_instance())

    task = swebench_to_coding_task(
        instance,
        repo_path="/tmp/repo",
        max_steps=12,
        infer_allowed_paths=True,
    )

    assert instance.fail_to_pass == ["tests/test_parser.py::test_edge"]
    assert infer_swebench_allowed_paths(instance) == ["pkg/parser.py"]
    assert task.task_id == "swebench:repo__project-123"
    assert task.repo_path == "/tmp/repo"
    assert task.max_steps == 12
    assert task.allowed_paths == ["pkg/parser.py"]
    assert task.test_commands == [["python", "-m", "pytest", "tests/test_parser.py::test_edge"]]
    assert task.metadata["benchmark"] == "swe-bench"
    assert task.metadata["base_commit"] == "abc123"


def test_swebench_task_does_not_leak_gold_patch_paths_by_default():
    instance = SWEBenchInstance.from_mapping(_raw_instance())

    task = swebench_to_coding_task(instance)

    assert infer_swebench_allowed_paths(instance) == ["pkg/parser.py"]
    assert task.allowed_paths == []


def test_swebench_test_command_template_expands_tests():
    instance = SWEBenchInstance.from_mapping(_raw_instance())

    command = swebench_test_command(instance, ["tox", "-e", "py", "--", "{tests}"])

    assert command == ["tox", "-e", "py", "--", "tests/test_parser.py::test_edge"]


def test_load_swebench_instances_from_jsonl(tmp_path: Path):
    path = tmp_path / "instances.jsonl"
    path.write_text(json.dumps(_raw_instance()) + "\n")

    instances = load_swebench_instances(path)

    assert len(instances) == 1
    assert instances[0].instance_id == "repo__project-123"


def test_swebench_run_artifact_round_trip(tmp_path: Path):
    instance = SWEBenchInstance.from_mapping(_raw_instance())
    result = CodingRunResult(
        task_id="swebench:repo__project-123",
        agent="test_agent",
        success=True,
        steps=3,
        final_diff="diff --git a/pkg/parser.py b/pkg/parser.py",
        modified_files=["pkg/parser.py"],
        ledger={"concerns": []},
    )

    artifact = swebench_run_artifact(instance, result)
    out = tmp_path / "artifact.json"
    write_swebench_run_artifact(out, instance, result)

    assert artifact["instance_id"] == "repo__project-123"
    assert artifact["success"]
    assert json.loads(out.read_text())["modified_files"] == ["pkg/parser.py"]
