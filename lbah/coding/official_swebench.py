"""Operational helpers for replaying LBAH patches with the official SWE-bench harness."""

from __future__ import annotations

import json
import platform
import shlex
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Literal


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
