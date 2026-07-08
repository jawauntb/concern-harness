#!/usr/bin/env python
"""Generate a multi-candidate SWE-bench matrix in parallel Modal L4 workers."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import modal

from lbah.coding import (
    SWEBenchOfficialHarnessSpec,
    default_swebench_candidate_roles,
    swebench_candidate_id,
    write_swebench_candidate_matrix,
)


ROOT = Path(__file__).resolve().parents[1]
REMOTE_ROOT = Path("/workspace")
GPU = os.environ.get("LBAH_MODAL_GPU", "L4")
MAX_CONTAINERS = int(os.environ.get("LBAH_MODAL_MAX_CONTAINERS", "40"))


def _ignore_modal_mount(path: Path) -> bool:
    parts = set(path.parts)
    return bool(
        parts
        & {
            ".git",
            ".mypy_cache",
            ".pytest_cache",
            ".ruff_cache",
            "__pycache__",
            "build",
            "dist",
            "logs",
            "runs",
        }
    )


app = modal.App("lbah-swebench-tournament")

image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("git")
    .pip_install(
        "anthropic>=0.40",
        "click>=8.1",
        "httpx>=0.27",
        "pydantic>=2.5",
        "pyyaml>=6.0",
        "rich>=13.7",
    )
    .add_local_dir(ROOT, str(REMOTE_ROOT), copy=True, ignore=_ignore_modal_mount)
    .run_commands(f"cd {REMOTE_ROOT} && python -m pip install -e .")
)


def _modal_secrets() -> list[modal.Secret]:
    values: dict[str, str | None] = {
        key: value
        for key in ["ANTHROPIC_API_KEY", "OPENAI_API_KEY", "SAKANA_API_KEY"]
        if (value := os.environ.get(key))
    }
    return [modal.Secret.from_dict(values)] if values else []


@app.function(
    image=image,
    gpu=GPU,
    timeout=90 * 60,
    max_containers=MAX_CONTAINERS,
    secrets=_modal_secrets(),
)
def generate_candidate(
    job: dict[str, Any],
    model_config: str,
    *,
    max_steps: int,
    timeout_seconds: float,
    official_dataset: str,
    run_id: str,
) -> dict[str, Any]:
    raw_instance = dict(job["instance"])
    candidate_index = int(job["candidate_index"])
    candidate_count = int(job["candidate_count"])
    candidate_id = swebench_candidate_id(candidate_index)
    candidate_role = dict(job["candidate_role"])
    instance_id = str(raw_instance["instance_id"])
    raw_instance["problem_statement"] = _candidate_problem_statement(
        str(raw_instance.get("problem_statement", "")),
        candidate_index=candidate_index,
        candidate_count=candidate_count,
        role_label=str(candidate_role["role_label"]),
        prompt_note=str(candidate_role["prompt_note"]),
    )

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        instances_path = tmp_path / "instance.jsonl"
        model_path = tmp_path / "model.yaml"
        out_dir = tmp_path / "out"
        instances_path.write_text(json.dumps(raw_instance) + "\n")
        model_path.write_text(model_config)

        cmd = [
            "python",
            "-m",
            "lbah.cli",
            "code",
            "swebench",
            "--instances",
            str(instances_path),
            "--model-agent",
            str(model_path),
            "--official",
            "--official-dataset",
            official_dataset,
            "--official-run-id",
            f"{run_id}-{candidate_id}",
            "--subset-sizes",
            "1",
            "--limit",
            "1",
            "--max-steps",
            str(max_steps),
            "--timeout",
            str(timeout_seconds),
            "--skip-pass-to-pass",
            "--out",
            str(out_dir),
        ]
        proc = subprocess.run(
            cmd,
            cwd=REMOTE_ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        predictions_path = out_dir / "official" / "predictions.jsonl"
        runs_path = out_dir / "runs.jsonl"
        return {
            "instance_id": instance_id,
            "candidate_id": candidate_id,
            "candidate_index": candidate_index,
            "role_id": str(candidate_role["role_id"]),
            "role_label": str(candidate_role["role_label"]),
            "returncode": proc.returncode,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
            "prediction": predictions_path.read_text() if predictions_path.exists() else "",
            "run": runs_path.read_text() if runs_path.exists() else "",
        }


@app.local_entrypoint()
def main(
    instances: str,
    model_agent: str,
    out: str,
    official_dataset: str = "princeton-nlp/SWE-bench_Lite",
    run_id: str = "lbah-modal-candidates",
    candidates_per_instance: int = 3,
    max_workers: int = 20,
    limit: int = 5,
    offset: int = 0,
    max_steps: int = 20,
    timeout_seconds: float = 120.0,
    strict: bool = True,
) -> None:
    if candidates_per_instance < 1:
        raise SystemExit("--candidates-per-instance must be at least 1")
    rows = [
        json.loads(line)
        for line in Path(instances).read_text().splitlines()
        if line.strip()
    ][offset : offset + limit]
    candidate_ids = [swebench_candidate_id(index) for index in range(candidates_per_instance)]
    candidate_roles = default_swebench_candidate_roles(candidate_ids)
    role_by_candidate = {role.candidate_id: role for role in candidate_roles}
    jobs = [
        {
            "instance": row,
            "candidate_index": index,
            "candidate_count": candidates_per_instance,
            "candidate_role": role_by_candidate[swebench_candidate_id(index)].model_dump(),
        }
        for row in rows
        for index in range(candidates_per_instance)
    ]
    model_config = Path(model_agent).read_text()
    results = list(
        generate_candidate.map(
            jobs,
            kwargs={
                "model_config": model_config,
                "max_steps": max_steps,
                "timeout_seconds": timeout_seconds,
                "official_dataset": official_dataset,
                "run_id": run_id,
            },
            order_outputs=True,
        )
    )

    destination = Path(out)
    spec = SWEBenchOfficialHarnessSpec(
        dataset_name=official_dataset,
        run_id=run_id,
        max_workers=max_workers,
        cache_level="env",
        modal=True,
    )
    manifest = write_swebench_candidate_matrix(
        destination,
        results,
        spec=spec,
        instance_ids=[str(row["instance_id"]) for row in rows],
        candidate_ids=candidate_ids,
        candidate_roles=candidate_roles,
        subset_sizes=[len(rows)],
        strict=strict,
    )
    print(
        f"wrote {len(results)} candidate generations across "
        f"{manifest.candidate_count} candidates to {destination}"
    )


def _candidate_problem_statement(
    problem_statement: str,
    *,
    candidate_index: int,
    candidate_count: int,
    role_label: str,
    prompt_note: str,
) -> str:
    return (
        f"{problem_statement}\n\n"
        "Harness candidate note: this is independent candidate "
        f"{candidate_index + 1} of {candidate_count} with role `{role_label}`. "
        f"{prompt_note} Explore a distinct plausible repair path instead of "
        "copying the most obvious first attempt. Do not add comments that "
        "mention this note."
    )
