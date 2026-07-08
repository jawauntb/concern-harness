from __future__ import annotations

import json
from pathlib import Path

from lbah.coding.official_swebench import (
    DopplerRunConfig,
    load_official_swebench_command,
    plan_official_swebench_run,
)


def _base_command() -> list[str]:
    return [
        "python",
        "-m",
        "swebench.harness.run_evaluation",
        "--dataset_name",
        "princeton-nlp/SWE-bench_Lite",
        "--predictions_path",
        "predictions.jsonl",
        "--max_workers",
        "1",
        "--run_id",
        "lbah-code",
        "--cache_level",
        "env",
        "--instance_ids",
        "django__django-100",
        "sympy__sympy-200",
    ]


def test_loads_run_command_or_subset_manifest(tmp_path: Path):
    run_path = tmp_path / "run_evaluation_command.json"
    subset_path = tmp_path / "n5.json"
    run_path.write_text(json.dumps({"command": _base_command()}))
    subset_path.write_text(json.dumps({"official_command": _base_command()}))

    assert load_official_swebench_command(run_path) == _base_command()
    assert load_official_swebench_command(subset_path) == _base_command()


def test_modal_plan_inserts_flags_before_instance_ids():
    plan = plan_official_swebench_run(
        _base_command(),
        target="modal",
        max_workers=8,
        run_id="lbah-modal-n5",
        cache_level="instance",
    )

    assert plan.command[plan.command.index("--max_workers") + 1] == "8"
    assert plan.command[plan.command.index("--run_id") + 1] == "lbah-modal-n5"
    assert plan.command[plan.command.index("--cache_level") + 1] == "instance"
    assert plan.command[plan.command.index("--modal") + 1] == "true"
    assert plan.command.index("--modal") < plan.command.index("--instance_ids")


def test_modal_gpu_request_is_reported_as_upstream_grader_limitation():
    plan = plan_official_swebench_run(
        _base_command(),
        target="modal",
        modal_gpu="L4",
    )

    assert any("requested 'L4' is ignored" in warning for warning in plan.warnings)


def test_doppler_wrapper_keeps_command_shell_safe():
    plan = plan_official_swebench_run(
        _base_command(),
        target="modal",
        use_doppler=True,
        doppler=DopplerRunConfig(project="cofounder", config="dev"),
    )

    assert plan.wrapped_command[:7] == [
        "doppler",
        "run",
        "--project",
        "cofounder",
        "--config",
        "dev",
        "--",
    ]
    assert "swebench.harness.run_evaluation" in plan.shell_command()


def test_local_plan_warns_on_low_disk_without_failing():
    plan = plan_official_swebench_run(_base_command(), target="local")

    assert plan.command[:3] == ["python", "-m", "swebench.harness.run_evaluation"]
    assert isinstance(plan.warnings, list)
