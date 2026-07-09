"""SWE-bench-style checkout, evaluation, and artifact orchestration."""

from __future__ import annotations

import json
import re
import shlex
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, Callable, Iterable, Literal

from pydantic import BaseModel, Field

from .actions import CodingTask
from .runner import CodingHarnessRunner, CodingRunResult
from .swebench import SWEBenchInstance, swebench_to_coding_task
from .workspace import CodingWorkspace, CommandResult


SWEBenchBackendKind = Literal["local", "docker"]
SWEBenchFailureKind = Literal[
    "success",
    "checkout_failed",
    "test_patch_failed",
    "harness_error",
    "agent_failed",
    "no_patch",
    "fail_to_pass_failed",
    "pass_to_pass_failed",
]
AgentFactory = Callable[[SWEBenchInstance, CodingTask], Any]


class SWEBenchExecutionBackend(BaseModel):
    """How benchmark test commands should execute."""

    kind: SWEBenchBackendKind = "local"
    docker_image: str | None = None
    docker_extra_args: list[str] = Field(default_factory=list)
    timeout_seconds: float = 300.0

    def wrap_command(self, command: list[str] | str, repo_dir: str | Path) -> list[str]:
        cmd = _normalize_command(command)
        if self.kind == "local":
            return cmd
        if not self.docker_image:
            raise ValueError("docker backend requires docker_image")
        return [
            "docker",
            "run",
            "--rm",
            "-v",
            f"{Path(repo_dir).resolve()}:/workspace",
            "-w",
            "/workspace",
            *self.docker_extra_args,
            self.docker_image,
            *cmd,
        ]

    def run(self, command: list[str] | str, repo_dir: str | Path) -> CommandResult:
        wrapped = self.wrap_command(command, repo_dir)
        return _run_command(wrapped, Path(repo_dir), self.timeout_seconds)


class SWEBenchEvaluationOptions(BaseModel):
    """Controls one or more SWE-bench-style instance evaluations."""

    repo_source: str | None = None
    repo_root: str | None = None
    work_dir: str | None = None
    out_dir: str | None = None
    max_steps: int = 40
    timeout_seconds: float = 300.0
    test_command_template: list[str] | str | None = None
    allowed_paths: list[str] | None = None
    infer_allowed_paths: bool = False
    include_pass_to_pass: bool = True
    clean_work_dir: bool = True
    backend: SWEBenchExecutionBackend = Field(default_factory=SWEBenchExecutionBackend)


class SWEBenchPreparedWorkspace(BaseModel):
    """Repository workspace prepared for one benchmark instance."""

    instance_id: str
    repo: str
    repo_dir: str
    source: str
    base_commit: str | None = None
    checkout: CommandResult | None = None
    test_patch: CommandResult | None = None


class SWEBenchEvaluationResult(BaseModel):
    """Comparable output for one SWE-bench-style instance run."""

    benchmark: str = "swe-bench"
    instance_id: str
    repo: str
    success: bool
    failure_kind: SWEBenchFailureKind
    task_id: str | None = None
    agent: str | None = None
    checkout: SWEBenchPreparedWorkspace | None = None
    coding_result: CodingRunResult | None = None
    fail_to_pass_results: list[CommandResult] = Field(default_factory=list)
    pass_to_pass_results: list[CommandResult] = Field(default_factory=list)
    final_diff: str = ""
    modified_files: list[str] = Field(default_factory=list)
    artifact_dir: str | None = None
    error: str | None = None
    wall_time_seconds: float = 0.0


class SWEBenchSuiteResult(BaseModel):
    """Aggregate summary for a small SWE-bench smoke run."""

    benchmark: str = "swe-bench"
    total: int
    solved: int
    solve_rate: float
    failure_counts: dict[str, int] = Field(default_factory=dict)
    results: list[SWEBenchEvaluationResult] = Field(default_factory=list)


SWEBenchCacheLevel = Literal["none", "base", "env", "instance"]


class SWEBenchOfficialHarnessSpec(BaseModel):
    """Command contract for the official Docker-based SWE-bench harness."""

    dataset_name: str = "princeton-nlp/SWE-bench_Verified"
    split: str = "test"
    run_id: str = "lbah-code"
    max_workers: int = 1
    cache_level: SWEBenchCacheLevel = "env"
    timeout: int | None = None
    namespace: str | None = None
    modal: bool = False
    clean: bool = True


class SWEBenchOfficialHarnessInputs(BaseModel):
    """Files and command needed to replay LBAH patches in the official harness."""

    predictions_path: str
    instance_ids_path: str
    command_path: str
    command: list[str]
    instance_ids: list[str]
    dataset_name: str
    run_id: str


class SWEBenchSubsetManifest(BaseModel):
    """Stable measured-subset manifest for repeated n=5/n=20/n=50 runs."""

    name: str
    size: int
    instance_ids: list[str]
    predictions_path: str | None = None
    official_command: list[str] = Field(default_factory=list)


class SWEBenchPreparationError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        kind: Literal["checkout_failed", "test_patch_failed"],
        checkout: SWEBenchPreparedWorkspace | None = None,
        command_result: CommandResult | None = None,
    ):
        super().__init__(message)
        self.kind: Literal["checkout_failed", "test_patch_failed"] = kind
        self.checkout: SWEBenchPreparedWorkspace | None = checkout
        self.command_result: CommandResult | None = command_result


def sanitize_swebench_id(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("_") or "instance"


def resolve_swebench_repo_source(
    instance: SWEBenchInstance,
    *,
    repo_source: str | None = None,
    repo_root: str | None = None,
) -> str:
    """Resolve a local source repo or GitHub clone URL for an instance."""

    if repo_source:
        return repo_source
    if repo_root:
        root = Path(repo_root)
        candidates = [
            root / Path(*instance.repo.split("/")),
            root / instance.repo.replace("/", "__"),
            root / instance.repo.split("/")[-1],
        ]
        for candidate in candidates:
            if candidate.exists():
                return str(candidate)
    return f"https://github.com/{instance.repo}.git"


def prepare_swebench_workspace(
    instance: SWEBenchInstance,
    options: SWEBenchEvaluationOptions,
) -> SWEBenchPreparedWorkspace:
    parent = _workspace_parent(options)
    repo_dir = parent / sanitize_swebench_id(instance.instance_id)
    if repo_dir.exists() and options.clean_work_dir:
        shutil.rmtree(repo_dir)
    parent.mkdir(parents=True, exist_ok=True)

    source = resolve_swebench_repo_source(
        instance,
        repo_source=options.repo_source,
        repo_root=options.repo_root,
    )
    checkout_result = _checkout_source(source, repo_dir, instance.base_commit, options.timeout_seconds)
    prepared = SWEBenchPreparedWorkspace(
        instance_id=instance.instance_id,
        repo=instance.repo,
        repo_dir=str(repo_dir),
        source=source,
        base_commit=instance.base_commit,
        checkout=checkout_result,
    )
    if not checkout_result.passed:
        raise SWEBenchPreparationError(
            "repository checkout failed",
            kind="checkout_failed",
            checkout=prepared,
            command_result=checkout_result,
        )

    if instance.test_patch:
        patch_result = _apply_patch(repo_dir, instance.test_patch, options.timeout_seconds)
        prepared.test_patch = patch_result
        if not patch_result.passed:
            raise SWEBenchPreparationError(
                "test patch failed to apply",
                kind="test_patch_failed",
                checkout=prepared,
                command_result=patch_result,
            )

    # Track D / §4.4 (b): plant on-disk leak carrier when the instance JSONL
    # was produced by ``inject_leaks_into_instances``. Official grading still
    # applies model_patch to a clean base, so this file never reaches the grader.
    from .contamination.inject import write_leak_carrier_from_instance

    write_leak_carrier_from_instance(repo_dir, instance)
    return prepared


def run_swebench_instance(
    instance: SWEBenchInstance,
    agent_factory: AgentFactory,
    options: SWEBenchEvaluationOptions | None = None,
) -> SWEBenchEvaluationResult:
    opts = options or SWEBenchEvaluationOptions()
    started_at = time.time()
    artifact_dir = _artifact_dir(opts, instance)
    checkout: SWEBenchPreparedWorkspace | None = None
    task: CodingTask | None = None
    coding_result: CodingRunResult | None = None
    fail_to_pass_results: list[CommandResult] = []
    pass_to_pass_results: list[CommandResult] = []
    agent_name: str | None = None
    error: str | None = None

    try:
        checkout = prepare_swebench_workspace(instance, opts)
        task = swebench_to_coding_task(
            instance,
            repo_path=checkout.repo_dir,
            max_steps=opts.max_steps,
            test_command_template=opts.test_command_template,
            allowed_paths=opts.allowed_paths,
            infer_allowed_paths=opts.infer_allowed_paths,
        )
        if opts.backend.kind == "docker":
            task = _docker_wrapped_task(task, opts.backend, checkout.repo_dir)
        agent = agent_factory(instance, task)
        agent_name = getattr(agent, "name", "coding_agent")
        workspace = CodingWorkspace(checkout.repo_dir, task, timeout_seconds=opts.timeout_seconds)
        coding_result = CodingHarnessRunner(agent, workspace).run(task)
        fail_to_pass_results = run_swebench_tests(
            instance.fail_to_pass,
            checkout.repo_dir,
            opts.backend,
            opts.test_command_template,
        )
        if opts.include_pass_to_pass:
            pass_to_pass_results = run_swebench_tests(
                instance.pass_to_pass,
                checkout.repo_dir,
                opts.backend,
                opts.test_command_template,
            )
    except SWEBenchPreparationError as exc:
        checkout = exc.checkout
        error = str(exc)
        failure_kind: SWEBenchFailureKind = exc.kind
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        failure_kind = "harness_error"
    else:
        failure_kind = classify_swebench_failure(
            coding_result,
            fail_to_pass_results,
            pass_to_pass_results,
        )

    result = SWEBenchEvaluationResult(
        instance_id=instance.instance_id,
        repo=instance.repo,
        success=failure_kind == "success",
        failure_kind=failure_kind,
        task_id=task.task_id if task else None,
        agent=agent_name,
        checkout=checkout,
        coding_result=coding_result,
        fail_to_pass_results=fail_to_pass_results,
        pass_to_pass_results=pass_to_pass_results,
        final_diff=coding_result.final_diff if coding_result else "",
        modified_files=coding_result.modified_files if coding_result else [],
        artifact_dir=str(artifact_dir) if artifact_dir else None,
        error=error,
        wall_time_seconds=time.time() - started_at,
    )
    if artifact_dir:
        write_swebench_evaluation_artifacts(artifact_dir, instance, task, result)
    return result


def run_swebench_smoke_suite(
    instances: list[SWEBenchInstance],
    agent_factory: AgentFactory,
    options: SWEBenchEvaluationOptions,
) -> SWEBenchSuiteResult:
    out_dir = Path(options.out_dir) if options.out_dir else None
    if out_dir:
        out_dir.mkdir(parents=True, exist_ok=True)

    results: list[SWEBenchEvaluationResult] = []
    for instance in instances:
        results.append(run_swebench_instance(instance, agent_factory, options))

    suite = summarize_swebench_results(results)
    if out_dir:
        (out_dir / "runs.jsonl").write_text(
            "\n".join(result.model_dump_json() for result in results) + ("\n" if results else "")
        )
        (out_dir / "summary.json").write_text(suite.model_dump_json(indent=2))
    return suite


def swebench_prediction_rows(
    results: Iterable[SWEBenchEvaluationResult],
    *,
    model_name_or_path: str = "lbah-code",
    include_empty: bool = True,
) -> list[dict[str, str]]:
    """Convert LBAH run results into official SWE-bench prediction rows."""

    rows: list[dict[str, str]] = []
    for result in results:
        if not include_empty and not result.final_diff:
            continue
        model_patch = result.final_diff
        if model_patch and not model_patch.endswith("\n"):
            model_patch += "\n"
        rows.append(
            {
                "instance_id": result.instance_id,
                "model_name_or_path": model_name_or_path,
                "model_patch": model_patch,
            }
        )
    return rows


def write_swebench_predictions(
    path: str | Path,
    results: Iterable[SWEBenchEvaluationResult],
    *,
    model_name_or_path: str = "lbah-code",
    include_empty: bool = True,
) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    rows = swebench_prediction_rows(
        results,
        model_name_or_path=model_name_or_path,
        include_empty=include_empty,
    )
    destination.write_text("\n".join(json.dumps(row) for row in rows) + ("\n" if rows else ""))
    return destination


def official_swebench_command(
    spec: SWEBenchOfficialHarnessSpec,
    *,
    predictions_path: str | Path,
    instance_ids: list[str] | None = None,
) -> list[str]:
    command = [
        "python",
        "-m",
        "swebench.harness.run_evaluation",
        "--dataset_name",
        spec.dataset_name,
        "--split",
        spec.split,
        "--predictions_path",
        str(predictions_path),
        "--max_workers",
        str(spec.max_workers),
        "--run_id",
        spec.run_id,
        "--cache_level",
        spec.cache_level,
        "--clean",
        str(spec.clean),
    ]
    if spec.timeout is not None:
        command.extend(["--timeout", str(spec.timeout)])
    if spec.namespace:
        command.extend(["--namespace", spec.namespace])
    if spec.modal:
        command.extend(["--modal", "true"])
    if instance_ids:
        command.append("--instance_ids")
        command.extend(instance_ids)
    return command


def write_official_swebench_inputs(
    out_dir: str | Path,
    results: Iterable[SWEBenchEvaluationResult],
    *,
    spec: SWEBenchOfficialHarnessSpec | None = None,
    model_name_or_path: str = "lbah-code",
) -> SWEBenchOfficialHarnessInputs:
    active_spec = spec or SWEBenchOfficialHarnessSpec()
    destination = Path(out_dir)
    destination.mkdir(parents=True, exist_ok=True)
    result_list = list(results)
    predictions_path = write_swebench_predictions(
        destination / "predictions.jsonl",
        result_list,
        model_name_or_path=model_name_or_path,
    )
    instance_ids = [result.instance_id for result in result_list]
    instance_ids_path = destination / "instance_ids.txt"
    instance_ids_path.write_text("\n".join(instance_ids) + ("\n" if instance_ids else ""))
    command = official_swebench_command(
        active_spec,
        predictions_path=predictions_path,
        instance_ids=instance_ids,
    )
    command_path = destination / "run_evaluation_command.json"
    command_path.write_text(
        json.dumps(
            {
                "command": command,
                "spec": active_spec.model_dump(),
                "source": "official swebench.harness.run_evaluation contract",
            },
            indent=2,
            sort_keys=True,
        )
    )
    return SWEBenchOfficialHarnessInputs(
        predictions_path=str(predictions_path),
        instance_ids_path=str(instance_ids_path),
        command_path=str(command_path),
        command=command,
        instance_ids=instance_ids,
        dataset_name=active_spec.dataset_name,
        run_id=active_spec.run_id,
    )


def build_swebench_subset_manifests(
    instance_ids: list[str],
    *,
    sizes: Iterable[int] = (5, 20, 50),
    predictions_path: str | None = None,
    spec: SWEBenchOfficialHarnessSpec | None = None,
) -> list[SWEBenchSubsetManifest]:
    active_spec = spec or SWEBenchOfficialHarnessSpec()
    manifests: list[SWEBenchSubsetManifest] = []
    for size in sizes:
        selected = instance_ids[: max(size, 0)]
        command = (
            official_swebench_command(
                active_spec,
                predictions_path=predictions_path,
                instance_ids=selected,
            )
            if predictions_path is not None
            else []
        )
        manifests.append(
            SWEBenchSubsetManifest(
                name=f"n{size}",
                size=size,
                instance_ids=selected,
                predictions_path=predictions_path,
                official_command=command,
            )
        )
    return manifests


def write_swebench_subset_manifests(
    out_dir: str | Path,
    instance_ids: list[str],
    *,
    sizes: Iterable[int] = (5, 20, 50),
    predictions_path: str | None = None,
    spec: SWEBenchOfficialHarnessSpec | None = None,
) -> list[SWEBenchSubsetManifest]:
    destination = Path(out_dir)
    destination.mkdir(parents=True, exist_ok=True)
    manifests = build_swebench_subset_manifests(
        instance_ids,
        sizes=sizes,
        predictions_path=predictions_path,
        spec=spec,
    )
    for manifest in manifests:
        (destination / f"{manifest.name}.json").write_text(manifest.model_dump_json(indent=2))
    return manifests


def summarize_swebench_results(results: list[SWEBenchEvaluationResult]) -> SWEBenchSuiteResult:
    failure_counts: dict[str, int] = {}
    for result in results:
        failure_counts[result.failure_kind] = failure_counts.get(result.failure_kind, 0) + 1
    solved = sum(1 for result in results if result.success)
    total = len(results)
    return SWEBenchSuiteResult(
        total=total,
        solved=solved,
        solve_rate=solved / total if total else 0.0,
        failure_counts=failure_counts,
        results=results,
    )


def run_swebench_tests(
    tests: list[str],
    repo_dir: str | Path,
    backend: SWEBenchExecutionBackend | None = None,
    template: list[str] | str | None = None,
) -> list[CommandResult]:
    commands = swebench_eval_commands(tests, template)
    active_backend = backend or SWEBenchExecutionBackend()
    return [active_backend.run(command, repo_dir) for command in commands]


def swebench_eval_commands(
    tests: list[str],
    template: list[str] | str | None = None,
) -> list[list[str] | str]:
    if not tests:
        return []
    if template is None:
        return [["python", "-m", "pytest", *tests]]
    if isinstance(template, str):
        return [template.format(tests=" ".join(tests))]
    command: list[str] = []
    for part in template:
        if part == "{tests}":
            command.extend(tests)
        else:
            command.append(part.format(tests=" ".join(tests)))
    return [command]


def classify_swebench_failure(
    coding_result: CodingRunResult | None,
    fail_to_pass_results: list[CommandResult],
    pass_to_pass_results: list[CommandResult],
) -> SWEBenchFailureKind:
    if coding_result is None:
        return "harness_error"
    if not coding_result.final_diff:
        return "no_patch"
    if not _commands_passed(fail_to_pass_results):
        return "fail_to_pass_failed"
    if not _commands_passed(pass_to_pass_results):
        return "pass_to_pass_failed"
    if not coding_result.success:
        return "agent_failed"
    return "success"


def write_swebench_evaluation_artifacts(
    artifact_dir: str | Path,
    instance: SWEBenchInstance,
    task: CodingTask | None,
    result: SWEBenchEvaluationResult,
) -> None:
    destination = Path(artifact_dir)
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "instance.json").write_text(instance.model_dump_json(indent=2))
    (destination / "evaluation.json").write_text(result.model_dump_json(indent=2))
    (destination / "final.diff").write_text(result.final_diff)
    if task is not None:
        (destination / "task.json").write_text(task.model_dump_json(indent=2))
    if result.coding_result is not None:
        (destination / "coding_run.json").write_text(result.coding_result.model_dump_json(indent=2))
    logs_dir = destination / "logs"
    logs_dir.mkdir(exist_ok=True)
    (logs_dir / "fail_to_pass.json").write_text(
        json.dumps([item.model_dump() for item in result.fail_to_pass_results], indent=2)
    )
    (logs_dir / "pass_to_pass.json").write_text(
        json.dumps([item.model_dump() for item in result.pass_to_pass_results], indent=2)
    )


def _workspace_parent(options: SWEBenchEvaluationOptions) -> Path:
    if options.work_dir:
        return Path(options.work_dir)
    if options.out_dir:
        return Path(options.out_dir) / "workspaces"
    return Path(tempfile.mkdtemp(prefix="lbah-swebench-"))


def _artifact_dir(options: SWEBenchEvaluationOptions, instance: SWEBenchInstance) -> Path | None:
    if not options.out_dir:
        return None
    return Path(options.out_dir) / "instances" / sanitize_swebench_id(instance.instance_id)


def _checkout_source(
    source: str,
    repo_dir: Path,
    base_commit: str | None,
    timeout_seconds: float,
) -> CommandResult:
    source_path = Path(source).expanduser()
    if source_path.exists() and not _is_git_repo(source_path):
        shutil.copytree(source_path, repo_dir)
        if base_commit:
            return _run_command(["git", "checkout", "--quiet", base_commit], repo_dir, timeout_seconds)
        return CommandResult(command=["copytree", str(source_path), str(repo_dir)], returncode=0)

    clone_source = str(source_path) if source_path.exists() else source
    clone = _run_command(["git", "clone", "--quiet", clone_source, str(repo_dir)], Path.cwd(), timeout_seconds)
    if not clone.passed or not base_commit:
        return clone
    checkout = _run_command(["git", "checkout", "--quiet", base_commit], repo_dir, timeout_seconds)
    if checkout.passed:
        return checkout
    return CommandResult(
        command=checkout.command,
        returncode=checkout.returncode,
        stdout=(clone.stdout + "\n" + checkout.stdout).strip(),
        stderr=(clone.stderr + "\n" + checkout.stderr).strip(),
        timed_out=clone.timed_out or checkout.timed_out,
    )


def _is_git_repo(path: Path) -> bool:
    result = _run_command(["git", "rev-parse", "--is-inside-work-tree"], path, 10.0)
    return result.passed


def _apply_patch(repo_dir: Path, patch: str, timeout_seconds: float) -> CommandResult:
    return _run_command(["git", "apply", "--whitespace=nowarn", "-"], repo_dir, timeout_seconds, input_text=patch)


def _docker_wrapped_task(
    task: CodingTask,
    backend: SWEBenchExecutionBackend,
    repo_dir: str,
) -> CodingTask:
    return task.model_copy(
        update={
            "test_commands": [
                backend.wrap_command(command, repo_dir)
                for command in task.test_commands
            ]
        }
    )


def _normalize_command(command: list[str] | str) -> list[str]:
    cmd = shlex.split(command) if isinstance(command, str) else [str(part) for part in command]
    if not cmd:
        raise ValueError("empty command")
    return cmd


def _run_command(
    command: list[str],
    cwd: Path,
    timeout_seconds: float,
    *,
    input_text: str | None = None,
) -> CommandResult:
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            input=input_text,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
        return CommandResult(
            command=command,
            returncode=completed.returncode,
            stdout=completed.stdout[-8000:],
            stderr=completed.stderr[-8000:],
        )
    except subprocess.TimeoutExpired as exc:
        return CommandResult(
            command=command,
            returncode=124,
            stdout=(exc.stdout or "") if isinstance(exc.stdout, str) else "",
            stderr=(exc.stderr or "") if isinstance(exc.stderr, str) else "",
            timed_out=True,
        )
    except OSError as exc:
        return CommandResult(
            command=command,
            returncode=127,
            stderr=f"{type(exc).__name__}: {exc}",
        )


def _commands_passed(results: list[CommandResult]) -> bool:
    return all(result.passed for result in results)
