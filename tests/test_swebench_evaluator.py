from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from click.testing import CliRunner

from lbah.cli import cli
from lbah.coding import (
    CodingAction,
    CodingRunResult,
    SWEBenchEvaluationOptions,
    SWEBenchEvaluationResult,
    SWEBenchExecutionBackend,
    SWEBenchInstance,
    SWEBenchOfficialHarnessSpec,
    ScriptedCodingAgent,
    build_swebench_subset_manifests,
    classify_swebench_failure,
    official_swebench_command,
    prepare_swebench_workspace,
    resolve_swebench_repo_source,
    run_swebench_instance,
    run_swebench_smoke_suite,
    swebench_eval_commands,
    swebench_prediction_rows,
    write_official_swebench_inputs,
)
from lbah.coding.workspace import CommandResult


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        text=True,
        capture_output=True,
        check=True,
    )
    return result.stdout.strip()


def _source_repo(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "source_repo"
    (repo / "pkg").mkdir(parents=True)
    (repo / "tests").mkdir()
    (repo / "pkg" / "__init__.py").write_text("")
    (repo / "pkg" / "calc.py").write_text(
        "def add(a, b):\n"
        "    return a - b\n"
    )
    (repo / "tests" / "test_calc.py").write_text(
        "from pkg.calc import add\n\n"
        "\n"
        "def test_zero_rhs():\n"
        "    assert add(2, 0) == 2\n"
    )
    subprocess.run(["git", "-C", str(repo), "init"], check=True, capture_output=True)
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test User")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "initial")
    return repo, _git(repo, "rev-parse", "HEAD")


def _test_patch() -> str:
    return (
        "diff --git a/tests/test_calc.py b/tests/test_calc.py\n"
        "--- a/tests/test_calc.py\n"
        "+++ b/tests/test_calc.py\n"
        "@@ -3,3 +3,7 @@ from pkg.calc import add\n"
        "\n"
        " def test_zero_rhs():\n"
        "     assert add(2, 0) == 2\n"
        "+\n"
        "+\n"
        "+def test_adds_numbers():\n"
        "+    assert add(2, 3) == 5\n"
    )


def _instance(base_commit: str) -> SWEBenchInstance:
    return SWEBenchInstance.from_mapping(
        {
            "instance_id": "toy__calc-1",
            "repo": "toy/calc",
            "problem_statement": "Fix add so it returns the sum.",
            "base_commit": base_commit,
            "test_patch": _test_patch(),
            "FAIL_TO_PASS": ["tests/test_calc.py::test_adds_numbers"],
            "PASS_TO_PASS": ["tests/test_calc.py::test_zero_rhs"],
        }
    )


def _agent_factory(_instance: SWEBenchInstance, _task):
    return ScriptedCodingAgent(
        [
            CodingAction(
                action_id="edit",
                action_type="edit_file",
                payload={"path": "pkg/calc.py", "old": "return a - b", "new": "return a + b"},
                rationale="Fix the arithmetic operator.",
                concerns_addressed=["task", "risk_0", "risk_1", "risk_2", "risk_3"],
            ),
            CodingAction(action_id="tests", action_type="run_tests"),
            CodingAction(action_id="finish", action_type="finish"),
        ],
        name="scripted_fix",
    )


def test_resolve_repo_source_prefers_slugged_repo_root(tmp_path: Path):
    source, base_commit = _source_repo(tmp_path)
    repo_root = tmp_path / "repos"
    slugged = repo_root / "toy__calc"
    slugged.parent.mkdir()
    subprocess.run(["git", "clone", "--quiet", str(source), str(slugged)], check=True)

    resolved = resolve_swebench_repo_source(_instance(base_commit), repo_root=str(repo_root))

    assert resolved == str(slugged)


def test_prepare_workspace_clones_base_and_applies_test_patch(tmp_path: Path):
    source, base_commit = _source_repo(tmp_path)
    instance = _instance(base_commit)

    prepared = prepare_swebench_workspace(
        instance,
        SWEBenchEvaluationOptions(repo_source=str(source), work_dir=str(tmp_path / "work")),
    )

    repo_dir = Path(prepared.repo_dir)
    assert prepared.checkout and prepared.checkout.passed
    assert prepared.test_patch and prepared.test_patch.passed
    assert "test_adds_numbers" in (repo_dir / "tests" / "test_calc.py").read_text()
    assert _git(repo_dir, "rev-parse", "HEAD") == base_commit


def test_run_swebench_instance_writes_artifacts_and_succeeds(tmp_path: Path):
    source, base_commit = _source_repo(tmp_path)
    instance = _instance(base_commit)
    out_dir = tmp_path / "runs"

    result = run_swebench_instance(
        instance,
        _agent_factory,
        SWEBenchEvaluationOptions(
            repo_source=str(source),
            out_dir=str(out_dir),
            max_steps=5,
            test_command_template=[sys.executable, "-m", "pytest", "-q", "{tests}"],
        ),
    )

    assert result.success
    assert result.failure_kind == "success"
    assert result.modified_files == ["pkg/calc.py"]
    assert result.fail_to_pass_results[0].passed
    assert result.pass_to_pass_results[0].passed
    artifact_dir = out_dir / "instances" / "toy__calc-1"
    assert json.loads((artifact_dir / "evaluation.json").read_text())["success"]
    assert (artifact_dir / "final.diff").read_text()


def test_swebench_smoke_suite_writes_jsonl_and_summary(tmp_path: Path):
    source, base_commit = _source_repo(tmp_path)
    out_dir = tmp_path / "suite"

    suite = run_swebench_smoke_suite(
        [_instance(base_commit)],
        _agent_factory,
        SWEBenchEvaluationOptions(
            repo_source=str(source),
            out_dir=str(out_dir),
            max_steps=5,
            test_command_template=[sys.executable, "-m", "pytest", "-q", "{tests}"],
        ),
    )

    assert suite.solved == 1
    assert json.loads((out_dir / "summary.json").read_text())["solve_rate"] == 1.0
    assert len((out_dir / "runs.jsonl").read_text().splitlines()) == 1


def test_classify_failure_taxonomy_prefers_failed_fail_to_pass():
    assert classify_swebench_failure(
        coding_result=CodingRunResult(
            task_id="swebench:toy__calc-1",
            agent="scripted",
            success=True,
            steps=1,
            final_diff="diff",
            modified_files=["pkg/calc.py"],
            ledger={"concerns": []},
        ),
        fail_to_pass_results=[CommandResult(command=["pytest"], returncode=1)],
        pass_to_pass_results=[CommandResult(command=["pytest"], returncode=0)],
    ) == "fail_to_pass_failed"


def test_swebench_eval_commands_expands_test_placeholder():
    assert swebench_eval_commands(
        ["a::test_one", "b::test_two"],
        ["tox", "-e", "py", "--", "{tests}"],
    ) == [["tox", "-e", "py", "--", "a::test_one", "b::test_two"]]


def test_docker_backend_wraps_test_command_without_running_docker(tmp_path: Path):
    backend = SWEBenchExecutionBackend(kind="docker", docker_image="python:3.11")

    command = backend.wrap_command(["python", "-m", "pytest"], tmp_path)

    assert command[:3] == ["docker", "run", "--rm"]
    assert "-v" in command
    assert "python:3.11" in command
    assert command[-3:] == ["python", "-m", "pytest"]


def test_backend_records_missing_executable_as_command_result(tmp_path: Path):
    result = SWEBenchExecutionBackend().run(["definitely_missing_lbah_command"], tmp_path)

    assert result.returncode == 127
    assert "FileNotFoundError" in result.stderr


def test_official_prediction_rows_and_command_contract(tmp_path: Path):
    source, base_commit = _source_repo(tmp_path)
    result = run_swebench_instance(
        _instance(base_commit),
        _agent_factory,
        SWEBenchEvaluationOptions(
            repo_source=str(source),
            out_dir=str(tmp_path / "runs"),
            max_steps=5,
            test_command_template=[sys.executable, "-m", "pytest", "-q", "{tests}"],
        ),
    )
    spec = SWEBenchOfficialHarnessSpec(
        dataset_name="princeton-nlp/SWE-bench_Lite",
        run_id="lbah-test",
        max_workers=2,
        timeout=900,
    )

    rows = swebench_prediction_rows([result], model_name_or_path="lbah-test")
    command = official_swebench_command(
        spec,
        predictions_path=tmp_path / "predictions.jsonl",
        instance_ids=[result.instance_id],
    )

    assert rows == [
        {
            "instance_id": "toy__calc-1",
            "model_name_or_path": "lbah-test",
            "model_patch": result.final_diff,
        }
    ]
    assert command[:3] == ["python", "-m", "swebench.harness.run_evaluation"]
    assert "--dataset_name" in command
    assert "princeton-nlp/SWE-bench_Lite" in command
    assert "--instance_ids" in command
    assert "toy__calc-1" in command
    assert "--timeout" in command


def test_write_official_inputs_and_subset_manifests(tmp_path: Path):
    result = CodingRunResult(
        task_id="swebench:toy__calc-1",
        agent="scripted",
        success=True,
        steps=1,
        final_diff="diff --git a/pkg/calc.py b/pkg/calc.py",
        modified_files=["pkg/calc.py"],
        ledger={"concerns": []},
    )

    official_result = SWEBenchEvaluationResult(
        instance_id="toy__calc-1",
        repo="toy/calc",
        success=True,
        failure_kind="success",
        coding_result=result,
        final_diff=result.final_diff,
        modified_files=result.modified_files,
    )
    inputs = write_official_swebench_inputs(
        tmp_path / "official",
        [official_result],
        spec=SWEBenchOfficialHarnessSpec(run_id="lbah-test"),
    )
    manifests = build_swebench_subset_manifests(
        inputs.instance_ids,
        sizes=[1, 5],
        predictions_path=inputs.predictions_path,
        spec=SWEBenchOfficialHarnessSpec(run_id="lbah-test"),
    )

    assert Path(inputs.predictions_path).read_text().strip()
    assert Path(inputs.instance_ids_path).read_text().strip() == "toy__calc-1"
    assert json.loads(Path(inputs.command_path).read_text())["command"] == inputs.command
    assert [manifest.name for manifest in manifests] == ["n1", "n5"]
    assert manifests[1].instance_ids == ["toy__calc-1"]
    assert "--instance_ids" in manifests[0].official_command


def test_code_swebench_cli_runs_smoke_suite(tmp_path: Path):
    source, base_commit = _source_repo(tmp_path)
    instances_path = tmp_path / "instances.jsonl"
    actions_path = tmp_path / "actions.yaml"
    out_dir = tmp_path / "out"
    raw = _instance(base_commit).model_dump()
    raw["FAIL_TO_PASS"] = raw.pop("fail_to_pass")
    raw["PASS_TO_PASS"] = raw.pop("pass_to_pass")
    instances_path.write_text(json.dumps(raw) + "\n")
    actions_path.write_text(
        "name: scripted_fix\n"
        "actions:\n"
        "  - action_id: edit\n"
        "    action_type: edit_file\n"
        "    payload:\n"
        "      path: pkg/calc.py\n"
        "      old: return a - b\n"
        "      new: return a + b\n"
        "    rationale: Fix the arithmetic operator.\n"
        "    concerns_addressed: [task, risk_0, risk_1, risk_2, risk_3]\n"
        "  - action_id: tests\n"
        "    action_type: run_tests\n"
        "  - action_id: finish\n"
        "    action_type: finish\n"
    )

    result = CliRunner().invoke(
        cli,
        [
            "code",
            "swebench",
            "--instances",
            str(instances_path),
            "--repo-source",
            str(source),
            "--actions",
            str(actions_path),
            "--max-steps",
            "5",
            "--official",
            "--official-dataset",
            "princeton-nlp/SWE-bench_Lite",
            "--official-run-id",
            "lbah-test",
            "--subset-sizes",
            "1,5",
            "--out",
            str(out_dir),
        ],
    )

    assert result.exit_code == 0, result.output
    assert "solved=1/1" in result.output
    assert "official=" in result.output
    assert json.loads((out_dir / "summary.json").read_text())["solved"] == 1
    assert (out_dir / "official" / "predictions.jsonl").exists()
    assert (out_dir / "official" / "subsets" / "n1.json").exists()
