"""Sealed harness: git history wipe + network command blocks."""

from __future__ import annotations

import subprocess
from pathlib import Path

from lbah.coding.actions import CodingTask
from lbah.coding.swebench import SWEBenchInstance, swebench_to_coding_task
from lbah.coding.swebench_eval import seal_workspace_git_history
from lbah.coding.workspace import CodingWorkspace, _command_looks_networked


def test_seal_workspace_makes_single_commit(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "a.py").write_text("x = 1\n")
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-m", "one"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    (repo / "a.py").write_text("x = 2\n")
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-m", "two"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    before = subprocess.run(
        ["git", "rev-list", "--count", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    assert int(before.stdout.strip()) >= 2

    result = seal_workspace_git_history(repo, 30.0)
    assert result.passed
    after = subprocess.run(
        ["git", "rev-list", "--count", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    assert int(after.stdout.strip()) == 1
    log = subprocess.run(
        ["git", "log", "--oneline"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    assert "sealed base" in log.stdout


def test_command_looks_networked() -> None:
    assert _command_looks_networked(["curl", "https://example.com"])
    assert _command_looks_networked(["git", "clone", "https://github.com/x/y"])
    assert _command_looks_networked(["git", "fetch", "origin"])
    assert not _command_looks_networked(["git", "status"])
    assert not _command_looks_networked(["python", "-m", "pytest", "-q"])


def test_sealed_workspace_blocks_curl(tmp_path: Path) -> None:
    task = CodingTask(
        task_id="t",
        instruction="x",
        metadata={"seal_git_history": True},
    )
    ws = CodingWorkspace(tmp_path, task)
    blocked = ws.run_command(["curl", "https://example.com"])
    assert blocked.returncode == 126
    assert "sealed harness" in blocked.stderr


def test_swebench_task_unsealed_allows_git() -> None:
    inst = SWEBenchInstance(
        instance_id="toy__1",
        repo="toy/r",
        problem_statement="fix",
        patch="diff --git a/x b/x\n+hi\n",
    )
    sealed = swebench_to_coding_task(inst, seal_git_history=True)
    assert sealed.metadata["seal_git_history"] is True
    assert ".git" in sealed.disallowed_paths

    unsealed = swebench_to_coding_task(inst, allow_git_history=True)
    assert unsealed.metadata["allow_git_history"] is True
    assert ".git" not in unsealed.disallowed_paths
