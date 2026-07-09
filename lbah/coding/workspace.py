"""Workspace operations for real-repository coding agents."""

from __future__ import annotations

import difflib
import os
import shlex
import shutil
import subprocess
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from .actions import CodingTask


class CommandResult(BaseModel):
    command: list[str]
    returncode: int
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False

    @property
    def passed(self) -> bool:
        return self.returncode == 0 and not self.timed_out


class CodingWorkspace:
    """Guarded file and command operations rooted at a repository path."""

    def __init__(self, root: str | os.PathLike, task: CodingTask, timeout_seconds: float = 30.0):
        self.root = Path(root).resolve()
        self.task = task
        self.timeout_seconds = timeout_seconds
        self._baseline = self._snapshot_files()

    def _snapshot_files(self) -> dict[str, str]:
        files: dict[str, str] = {}
        for path in self.root.rglob("*"):
            if not path.is_file():
                continue
            rel = path.relative_to(self.root).as_posix()
            if self._is_disallowed(rel):
                continue
            try:
                files[rel] = path.read_text()
            except UnicodeDecodeError:
                continue
        return files

    def _is_disallowed(self, rel: str) -> bool:
        parts = Path(rel).parts
        return any(
            rel == item
            or rel.startswith(f"{item.rstrip('/')}/")
            or item in parts
            for item in self.task.disallowed_paths
        )

    def _resolve(self, rel_path: str) -> Path:
        candidate = (self.root / rel_path).resolve()
        if candidate != self.root and self.root not in candidate.parents:
            raise ValueError(f"path escapes workspace: {rel_path}")
        rel = candidate.relative_to(self.root).as_posix()
        if self._is_disallowed(rel):
            raise ValueError(f"path is disallowed: {rel_path}")
        return candidate

    def inspect(self) -> dict[str, Any]:
        return {
            "root": str(self.root),
            "modified_files": self.modified_files(),
            "test_commands": self.task.test_commands,
            "allowed_paths": self.task.allowed_paths,
        }

    def read_file(self, rel_path: str, start: int = 1, limit: int = 200) -> str:
        path = self._resolve(rel_path)
        lines = path.read_text().splitlines()
        zero_based = max(start - 1, 0)
        selected = lines[zero_based : zero_based + max(limit, 1)]
        return "\n".join(
            f"{line_no}: {line}"
            for line_no, line in enumerate(selected, start=zero_based + 1)
        )

    def search(self, pattern: str, glob: str | None = None, limit: int = 50) -> list[str]:
        rg = shutil.which("rg")
        if rg:
            cmd = [rg, "-n", pattern]
            if glob:
                cmd.extend(["-g", glob])
            result = subprocess.run(
                cmd,
                cwd=self.root,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
            )
            lines = result.stdout.splitlines()
            return lines[:limit]
        matches: list[str] = []
        for path in self.root.rglob(glob or "*"):
            if not path.is_file():
                continue
            rel = path.relative_to(self.root).as_posix()
            if self._is_disallowed(rel):
                continue
            try:
                for line_no, line in enumerate(path.read_text().splitlines(), start=1):
                    if pattern in line:
                        matches.append(f"{rel}:{line_no}:{line}")
                        if len(matches) >= limit:
                            return matches
            except UnicodeDecodeError:
                continue
        return matches

    def edit_file(self, rel_path: str, old: str | None = None, new: str | None = None, content: str | None = None) -> str:
        path = self._resolve(rel_path)
        before = path.read_text() if path.exists() else ""
        if content is not None:
            after = content
        elif old is not None and new is not None:
            if old not in before:
                raise ValueError(f"old text not found in {rel_path}")
            after = before.replace(old, new, 1)
        else:
            raise ValueError("edit_file requires either content or old+new")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(after)
        for cache_dir in path.parent.rglob("__pycache__"):
            shutil.rmtree(cache_dir, ignore_errors=True)
        return self.file_diff(rel_path, before, after)

    def run_command(self, command: list[str] | str, timeout_seconds: float | None = None) -> CommandResult:
        cmd = shlex.split(command) if isinstance(command, str) else [str(part) for part in command]
        if not cmd:
            raise ValueError("empty command")
        if self.task.metadata.get("seal_git_history") and _command_looks_networked(cmd):
            return CommandResult(
                command=cmd,
                returncode=126,
                stdout="",
                stderr=(
                    "sealed harness: network / remote-fetch commands are blocked "
                    f"({cmd[0]})"
                ),
            )
        try:
            result = subprocess.run(
                cmd,
                cwd=self.root,
                capture_output=True,
                text=True,
                timeout=timeout_seconds or self.timeout_seconds,
            )
            return CommandResult(
                command=cmd,
                returncode=result.returncode,
                stdout=result.stdout[-8000:],
                stderr=result.stderr[-8000:],
            )
        except subprocess.TimeoutExpired as exc:
            return CommandResult(
                command=cmd,
                returncode=124,
                stdout=(exc.stdout or "") if isinstance(exc.stdout, str) else "",
                stderr=(exc.stderr or "") if isinstance(exc.stderr, str) else "",
                timed_out=True,
            )

    def run_tests(self, commands: list[list[str] | str] | None = None) -> list[CommandResult]:
        return [self.run_command(command) for command in (commands or self.task.test_commands)]

    def file_diff(self, rel_path: str, before: str, after: str) -> str:
        return "\n".join(
            difflib.unified_diff(
                before.splitlines(),
                after.splitlines(),
                fromfile=f"a/{rel_path}",
                tofile=f"b/{rel_path}",
                lineterm="",
            )
        )

    def diff(self) -> str:
        chunks: list[str] = []
        current = self._snapshot_files()
        for rel in sorted(set(self._baseline) | set(current)):
            before = self._baseline.get(rel, "")
            after = current.get(rel, "")
            if before == after:
                continue
            chunks.append(self.file_diff(rel, before, after))
        return "\n".join(chunk for chunk in chunks if chunk)

    def modified_files(self) -> list[str]:
        current = self._snapshot_files()
        return [
            rel
            for rel in sorted(set(self._baseline) | set(current))
            if self._baseline.get(rel, "") != current.get(rel, "")
        ]

    def restore_baseline(self) -> list[str]:
        """Revert tracked text files to the post-checkout snapshot.

        Used by fail-closed contamination gating: if the synthetic leak marker
        is still in the commitment when the step budget is exhausted, wipe the
        working tree back so the submitted ``model_patch`` is empty rather than
        leaking a residual retrieved fingerprint.
        """

        current = self._snapshot_files()
        restored: list[str] = []
        for rel in sorted(set(self._baseline) | set(current)):
            before = self._baseline.get(rel)
            after = current.get(rel)
            if before == after:
                continue
            path = self.root / rel
            if before is None:
                if path.exists():
                    path.unlink()
                    restored.append(rel)
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(before)
            restored.append(rel)
        for cache_dir in self.root.rglob("__pycache__"):
            shutil.rmtree(cache_dir, ignore_errors=True)
        return restored

    def outside_allowed_paths(self) -> list[str]:
        if not self.task.allowed_paths:
            return []
        allowed = [p.rstrip("/") for p in self.task.allowed_paths]
        return [
            rel
            for rel in self.modified_files()
            if not any(rel == item or rel.startswith(f"{item}/") for item in allowed)
        ]


_NETWORK_BINARIES = {
    "curl",
    "wget",
    "http",
    "https",
    "nc",
    "ncat",
    "ssh",
    "scp",
    "sftp",
    "ftp",
    "aria2c",
}


def _command_looks_networked(cmd: list[str]) -> bool:
    """Best-effort block of remote-fetch / clone shells under a sealed harness.

    Not a full sandbox — Cursor's sealed eval also uses a network proxy. This
    catches the common agent patterns (curl/wget/git clone/fetch/pull) without
    blocking local ``git`` status/diff/add used by tooling.
    """

    if not cmd:
        return False
    binary = Path(cmd[0]).name.lower()
    if binary in _NETWORK_BINARIES:
        return True
    if binary == "git" and len(cmd) >= 2:
        sub = cmd[1].lower()
        if sub in {"clone", "fetch", "pull", "ls-remote", "remote"}:
            return True
    joined = " ".join(cmd).lower()
    if "https://" in joined or "http://" in joined or "git@" in joined:
        if binary in {"pytest", "python", "python3", "pip", "uv"}:
            return False
        return True
    return False
