#!/usr/bin/env python
"""Generate LBAH SWE-bench predictions in parallel Modal L4 workers."""

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
    official_swebench_command,
    write_swebench_subset_manifests,
)


ROOT = Path(__file__).resolve().parents[1]
REMOTE_ROOT = Path("/workspace")
GPU = os.environ.get("LBAH_MODAL_GPU", "L4")
MAX_CONTAINERS = int(os.environ.get("LBAH_MODAL_MAX_CONTAINERS", "20"))


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


app = modal.App("lbah-swebench-generate")

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
def generate_instance(
    raw_instance: dict[str, Any],
    model_config: str,
    *,
    max_steps: int,
    timeout_seconds: float,
    official_dataset: str,
    run_id: str,
    seal_git_history: bool = False,
    allow_git_history: bool = False,
    capture_io: bool = False,
    contamination_gate: bool = False,
    coding_prompt: str = "lbah",
) -> dict[str, Any]:
    instance_id = str(raw_instance["instance_id"])
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
            run_id,
            "--subset-sizes",
            "1",
            "--limit",
            "1",
            "--max-steps",
            str(max_steps),
            "--timeout",
            str(timeout_seconds),
            "--skip-pass-to-pass",
            "--coding-prompt",
            coding_prompt,
            "--out",
            str(out_dir),
        ]
        if seal_git_history:
            cmd.append("--seal-git-history")
        elif allow_git_history:
            cmd.append("--allow-git-history")
        if capture_io:
            cmd.append("--capture-io")
        if contamination_gate:
            cmd.append("--contamination-gate")
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
    run_id: str = "lbah-modal-l4",
    max_workers: int = 20,
    limit: int = 5,
    offset: int = 0,
    max_steps: int = 20,
    timeout_seconds: float = 120.0,
    seal_git_history: bool = False,
    allow_git_history: bool = False,
    capture_io: bool = False,
    contamination_gate: bool = False,
    coding_prompt: str = "lbah",
) -> None:
    rows = [
        json.loads(line)
        for line in Path(instances).read_text().splitlines()
        if line.strip()
    ][offset : offset + limit]
    model_config = Path(model_agent).read_text()
    destination = Path(out)
    official_dir = destination / "official"
    official_dir.mkdir(parents=True, exist_ok=True)
    if coding_prompt not in {"lbah", "raw"}:
        raise SystemExit("--coding-prompt must be 'lbah' or 'raw'")

    results = list(
        generate_instance.map(
            rows,
            kwargs={
                "model_config": model_config,
                "max_steps": max_steps,
                "timeout_seconds": timeout_seconds,
                "official_dataset": official_dataset,
                "run_id": run_id,
                "seal_git_history": seal_git_history,
                "allow_git_history": allow_git_history and not seal_git_history,
                "capture_io": capture_io,
                "contamination_gate": contamination_gate,
                "coding_prompt": coding_prompt,
            },
            order_outputs=True,
        )
    )
    failed = [
        result["instance_id"]
        for result in results
        if result["returncode"] != 0 or not result["prediction"].strip()
    ]
    if failed:
        raise SystemExit(f"generation failed or omitted predictions for: {', '.join(failed)}")

    (destination / "modal_generation_results.json").write_text(json.dumps(results, indent=2))
    predictions = [result["prediction"].strip() for result in results if result["prediction"].strip()]
    predictions_path = official_dir / "predictions.jsonl"
    instance_ids = [str(result["instance_id"]) for result in results]
    predictions_path.write_text("\n".join(predictions) + ("\n" if predictions else ""))
    (official_dir / "instance_ids.txt").write_text("\n".join(instance_ids) + ("\n" if results else ""))

    spec = SWEBenchOfficialHarnessSpec(
        dataset_name=official_dataset,
        run_id=run_id,
        max_workers=max_workers,
        cache_level="env",
        modal=True,
    )
    command = official_swebench_command(
        spec,
        predictions_path=predictions_path,
        instance_ids=instance_ids,
    )
    (official_dir / "run_evaluation_command.json").write_text(
        json.dumps(
            {
                "command": command,
                "spec": spec.model_dump(),
                "source": "Modal L4 LBAH generation handoff",
            },
            indent=2,
            sort_keys=True,
        )
    )
    write_swebench_subset_manifests(
        official_dir / "subsets",
        instance_ids,
        sizes=[len(instance_ids)],
        predictions_path=str(predictions_path),
        spec=spec,
    )
    print(f"wrote {len(predictions)} predictions to {predictions_path}")
