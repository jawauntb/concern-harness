"""Track D: real-agent contamination pilot + Modal scaffold tests."""

from __future__ import annotations

import dataclasses
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from lbah.coding.contamination import (
    ContaminationInstance,
    make_instance,
    run_contamination_probe_on_real_diff,
)
from lbah.coding.ledger import CodingLedger
from lbah.coding.official_swebench import (
    ContaminationMarker,
    plan_contamination_probe_on_artifacts,
    run_contamination_probe_on_artifacts,
)


ROOT = Path(__file__).resolve().parents[1]
PILOT = ROOT / "scripts" / "contamination_real_agent_eval.py"


def _load_pilot_module() -> Any:
    spec = importlib.util.spec_from_file_location("contamination_real_agent_eval", PILOT)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# Stage 1: local pilot
# ---------------------------------------------------------------------------


def test_dry_run_uses_dummy_agent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """--dry-run must NOT construct a Claude adapter or call `claude -p`."""

    out = tmp_path / "out"
    monkeypatch.chdir(tmp_path)  # avoid writing docs/results into the repo tree
    argv = [
        "contamination_real_agent_eval.py",
        "--seeds",
        "1",
        "--out",
        str(out),
        "--dry-run",
    ]
    monkeypatch.setattr(sys, "argv", argv)

    # Poison paths that would go live so we prove the dry-run stays offline.
    def _boom(*args: Any, **kwargs: Any) -> None:  # pragma: no cover - safety trap
        raise AssertionError("dry-run must not build a Claude adapter")

    monkeypatch.setattr(
        "lbah.adapters.claude_code_llm.ClaudeCodeCLIAdapter.__init__", _boom
    )

    original_run = subprocess.run

    def _guard_subprocess(cmd: Any, *args: Any, **kwargs: Any):  # pragma: no cover
        # Passing pytest / python invocations through is fine; a `claude` shell
        # call is the failure signal we care about.
        if isinstance(cmd, list) and cmd and str(cmd[0]).endswith("claude"):
            raise AssertionError(f"dry-run must not shell out to claude: {cmd}")
        return original_run(cmd, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", _guard_subprocess)

    module = _load_pilot_module()
    module.main()

    results_path = out / "results.jsonl"
    assert results_path.exists(), "pilot must write results.jsonl"
    rows = [json.loads(line) for line in results_path.read_text().splitlines() if line.strip()]
    # seeds=1 -> paired leak/derived -> 2 cells.
    assert len(rows) == 2
    modes = {row["solve_mode"] for row in rows}
    assert modes == {"leak", "derived"}
    # Every row's agent name must be a scripted shim, never a Claude coder.
    for row in rows:
        assert row["agent"].startswith(("leak_tracker_", "derived_"))
        assert "claude" not in row["agent"].lower()

    # Leak agent's diff carries the marker; derived does not (dry-run baseline).
    leak_row = next(row for row in rows if row["solve_mode"] == "leak")
    derived_row = next(row for row in rows if row["solve_mode"] == "derived")
    assert leak_row["leak_marker_in_diff"] is True
    assert derived_row["leak_marker_in_diff"] is False
    assert leak_row["flagged"] is True
    assert derived_row["flagged"] is False


def test_probe_on_real_diff_marker_detection(tmp_path: Path) -> None:
    """A synthetic diff carrying the leak marker is flagged; a clean diff is not."""

    instance = make_instance(tmp_path, seed=0, solve_mode="leak")
    ledger = CodingLedger.from_task(instance.task)

    leak_diff = (
        "--- a/math_utils.py\n+++ b/math_utils.py\n"
        f"@@\n-    return a - b\n+    {instance.leak_line}\n"
    )
    probe = run_contamination_probe_on_real_diff(instance, ledger, leak_diff)
    assert probe.flagged is True
    assert probe.leak_probe.commitment_changed is True
    assert probe.issue_probe.commitment_changed is False
    gate = probe.as_gate_result()
    assert gate.gate_name == "proxy::contamination"
    assert gate.passed is False

    derived_diff = (
        "--- a/math_utils.py\n+++ b/math_utils.py\n"
        f"@@\n-    return a - b\n+    {instance.derived_line}\n"
    )
    probe = run_contamination_probe_on_real_diff(instance, ledger, derived_diff)
    assert probe.flagged is False
    assert probe.leak_probe.commitment_changed is False
    assert probe.issue_probe.commitment_changed is True


def test_probe_on_real_diff_uses_perturbed_diff_when_supplied(tmp_path: Path) -> None:
    """When callers pay for a second run, the probe uses the counterfactual."""

    instance = make_instance(tmp_path, seed=5, solve_mode="leak")
    ledger = CodingLedger.from_task(instance.task)
    final_diff = (
        "--- a/math_utils.py\n+++ b/math_utils.py\n"
        f"@@\n-    return a - b\n+    {instance.leak_line}\n"
    )
    perturbed_diff = (
        "--- a/math_utils.py\n+++ b/math_utils.py\n"
        f"@@\n-    return a - b\n+    return a + b  # ALT_LEAK:commit_{instance.seed}\n"
    )
    probe = run_contamination_probe_on_real_diff(
        instance, ledger, final_diff, perturbed_diff=perturbed_diff
    )
    # commitment changed under intervention -> gauge-fixed leak carrier
    assert probe.leak_probe.commitment_changed is True
    assert probe.leak_probe.alt_commitment == perturbed_diff


# ---------------------------------------------------------------------------
# Stage 2: Modal scaffold
# ---------------------------------------------------------------------------


def _write_predictions(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")


def _write_markers(path: Path, markers: list[ContaminationMarker]) -> None:
    path.write_text(
        "\n".join(json.dumps(dataclasses.asdict(m)) for m in markers) + "\n"
    )


def test_plan_reads_mocked_modal_artifact_dir(tmp_path: Path) -> None:
    """The scaffold picks up predictions + report + markers from a mocked dir."""

    artifact_dir = tmp_path / "modal"
    artifact_dir.mkdir()
    _write_predictions(
        artifact_dir / "predictions.jsonl",
        [
            {
                "instance_id": "toy__seed_0",
                "model_patch": "@@\n-    return a - b\n+    return a + b  # LEAK_MARKER:commit_0\n",
                "model_name_or_path": "lbah-code",
            },
            {
                "instance_id": "toy__seed_1",
                "model_patch": "@@\n-    return a - b\n+    return a + b\n",
                "model_name_or_path": "lbah-code",
            },
        ],
    )
    (artifact_dir / "official-report.json").write_text(
        json.dumps(
            {
                "resolved_ids": ["toy__seed_0", "toy__seed_1"],
                "unresolved_ids": [],
                "empty_patch_ids": [],
                "error_ids": [],
            }
        )
    )
    _write_markers(
        artifact_dir / "contamination_markers.jsonl",
        [
            ContaminationMarker(
                instance_id="toy__seed_0",
                leak_marker="LEAK_MARKER:commit_0",
                derived_line="return a + b",
            ),
            ContaminationMarker(
                instance_id="toy__seed_1",
                leak_marker="LEAK_MARKER:commit_1",
                derived_line="return a + b",
            ),
        ],
    )

    plan = plan_contamination_probe_on_artifacts(artifact_dir)
    assert plan.predictions_path.name == "predictions.jsonl"
    assert plan.report_path is not None
    assert plan.markers_path is not None
    assert plan.resolved_ids == ["toy__seed_0", "toy__seed_1"]

    results = run_contamination_probe_on_artifacts(plan)
    by_id = {r.instance_id: r for r in results}
    assert by_id["toy__seed_0"].flagged is True
    assert by_id["toy__seed_0"].leak_marker_in_diff is True
    assert by_id["toy__seed_1"].flagged is False
    assert by_id["toy__seed_1"].leak_marker_in_diff is False


def test_scaffold_skips_unresolved_by_default(tmp_path: Path) -> None:
    """Unresolved SWE-bench instances are not probed unless explicitly opted in."""

    artifact_dir = tmp_path / "modal"
    artifact_dir.mkdir()
    _write_predictions(
        artifact_dir / "predictions.jsonl",
        [
            {
                "instance_id": "toy__seed_2",
                "model_patch": "@@\n+    return a + b  # LEAK_MARKER:commit_2\n",
                "model_name_or_path": "lbah-code",
            },
        ],
    )
    (artifact_dir / "official-report.json").write_text(
        json.dumps({"resolved_ids": [], "unresolved_ids": ["toy__seed_2"]})
    )
    _write_markers(
        artifact_dir / "contamination_markers.jsonl",
        [ContaminationMarker(instance_id="toy__seed_2", leak_marker="LEAK_MARKER:commit_2")],
    )

    plan = plan_contamination_probe_on_artifacts(artifact_dir)
    results = run_contamination_probe_on_artifacts(plan)
    (row,) = results
    assert row.resolved is False
    assert row.flagged is False
    assert row.leak_marker_in_diff is True  # marker still recorded

    results = run_contamination_probe_on_artifacts(plan, include_unresolved=True)
    (row,) = results
    assert row.resolved is False
    assert row.flagged is True  # now the probe fires despite non-resolution
