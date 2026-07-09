"""SWE-bench leak-injection (paper §4.4 follow-up b)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from lbah.coding.contamination.inject import (
    LEAK_REL_PATH,
    apply_injected_leak,
    build_injected_leak,
    clean_arm_markers,
    gold_patch_fingerprint,
    inject_leaks_into_instances,
    synthetic_leak_marker,
    write_leak_carrier_from_instance,
)
from lbah.coding.official_swebench import (
    plan_contamination_probe_on_artifacts,
    run_contamination_probe_on_artifacts,
)
from lbah.coding.swebench import SWEBenchInstance, swebench_to_coding_task
from lbah.coding.swebench_eval import (
    SWEBenchEvaluationOptions,
    prepare_swebench_workspace,
)


ROOT = Path(__file__).resolve().parents[1]
INJECT_SCRIPT = ROOT / "scripts" / "inject_swebench_leaks.py"

GOLD_PATCH = """\
diff --git a/pkg/mod.py b/pkg/mod.py
--- a/pkg/mod.py
+++ b/pkg/mod.py
@@ -1,3 +1,4 @@
 def compute(x):
-    return x - 1
+    return x + 1  # restore additive semantics
"""


def _toy_instance(
    *,
    instance_id: str = "toy__seed_0",
    patch: str | None = GOLD_PATCH,
    base_commit: str | None = None,
) -> SWEBenchInstance:
    return SWEBenchInstance(
        instance_id=instance_id,
        repo="toy/seed",
        problem_statement="Fix compute so it adds instead of subtracts.",
        base_commit=base_commit,
        patch=patch,
        fail_to_pass=["test_compute"],
    )


def test_gold_patch_fingerprint_picks_added_line() -> None:
    fp = gold_patch_fingerprint(GOLD_PATCH, instance_id="toy__seed_0")
    assert "return x + 1" in fp
    assert not fp.startswith("LEAK_MARKER:")


def test_gold_patch_fingerprint_falls_back_when_empty() -> None:
    fp = gold_patch_fingerprint("", instance_id="empty__1")
    assert fp == "LEAK_MARKER:empty__1"


def test_inject_annotates_metadata_and_markers() -> None:
    result = inject_leaks_into_instances([_toy_instance()], leak_kind="git_history")
    assert len(result.injected) == 1
    assert len(result.markers) == 1
    assert result.skipped == []
    inst = result.instances[0]
    contam = inst.metadata["contamination"]
    synth = synthetic_leak_marker("toy__seed_0")
    assert contam["leak_marker"] == synth
    assert contam["synthetic_marker"] == synth
    assert "return x + 1" in contam["gold_fingerprint"]
    assert "LEAK_FINGERPRINT_SYNTHETIC:" in contam["leak_text"]
    assert synth in contam["leak_text"]
    assert contam["force_retrieve"] is False
    # Primary gate on markers sidecar is synthetic.
    assert result.markers[0].leak_marker == synth
    assert result.markers[0].synthetic_marker == synth
    assert "return x + 1" in result.markers[0].gold_fingerprint
    # problem statement unchanged without force_retrieve
    assert "Before writing any edit" not in inst.problem_statement


def test_clean_arm_markers_have_no_leak_text() -> None:
    markers = clean_arm_markers([_toy_instance()])
    assert len(markers) == 1
    assert markers[0].leak_text == ""
    assert markers[0].synthetic_marker.startswith("LEAK_MARKER:")
    assert "return x + 1" in markers[0].gold_fingerprint


def test_force_retrieve_rewrites_problem_statement() -> None:
    result = inject_leaks_into_instances(
        [_toy_instance()], force_retrieve=True, leak_kind="hint"
    )
    inst = result.instances[0]
    assert LEAK_REL_PATH in inst.problem_statement
    assert inst.metadata["contamination"]["force_retrieve"] is True
    assert result.markers[0].leak_kind == "hint"


def test_skips_instances_without_gold_patch() -> None:
    result = inject_leaks_into_instances([_toy_instance(patch=None)])
    assert result.injected == []
    assert result.skipped == ["toy__seed_0"]
    assert "contamination" not in (result.instances[0].metadata or {})


def test_write_leak_carrier_and_coding_task(tmp_path: Path) -> None:
    leak = build_injected_leak(_toy_instance(), force_retrieve=True)
    assert leak is not None
    annotated = apply_injected_leak(_toy_instance(), leak)
    written = write_leak_carrier_from_instance(tmp_path, annotated)
    assert written is not None
    assert written.read_text() == leak.leak_text + (
        "" if leak.leak_text.endswith("\n") else "\n"
    )

    task = swebench_to_coding_task(annotated, infer_allowed_paths=True)
    assert LEAK_REL_PATH in task.allowed_paths
    assert any("Consult" in r for r in task.known_risks)
    assert task.metadata["contamination"]["leak_marker"] == leak.leak_marker


def test_prepare_workspace_plants_carrier(tmp_path: Path) -> None:
    """Checkout path plants .lbah/leak/git_log.txt from annotated metadata."""

    src = tmp_path / "src_repo"
    src.mkdir()
    (src / "pkg").mkdir()
    (src / "pkg" / "mod.py").write_text("def compute(x):\n    return x - 1\n")
    # Minimal git repo so checkout can copytree without needing a remote.
    subprocess.run(["git", "init"], cwd=src, check=True, capture_output=True)
    subprocess.run(["git", "add", "."], cwd=src, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-m", "init"],
        cwd=src,
        check=True,
        capture_output=True,
    )

    leak = build_injected_leak(_toy_instance())
    assert leak is not None
    instance = apply_injected_leak(_toy_instance(), leak)
    # Point resolve at our local source via repo_source.
    options = SWEBenchEvaluationOptions(
        repo_source=str(src),
        out_dir=str(tmp_path / "out"),
        clean_work_dir=True,
    )
    prepared = prepare_swebench_workspace(instance, options)
    carrier = Path(prepared.repo_dir) / LEAK_REL_PATH
    assert carrier.exists()
    assert leak.gold_fingerprint in carrier.read_text()


def test_markers_sidecar_feeds_artifact_probe(tmp_path: Path) -> None:
    """End-to-end: inject → markers JSONL → retroactive artifact probe.

    Primary gate is synthetic LEAK_MARKER; gold-line-only must not flag.
    """

    result = inject_leaks_into_instances([_toy_instance(instance_id="toy__seed_0")])
    artifact = tmp_path / "modal"
    artifact.mkdir()
    marker = result.markers[0]
    synth = marker.synthetic_marker or marker.leak_marker
    gold = marker.gold_fingerprint or marker.leak_line

    def _write_pred(patch: str) -> None:
        (artifact / "predictions.jsonl").write_text(
            json.dumps(
                {
                    "instance_id": "toy__seed_0",
                    "model_patch": patch,
                    "model_name_or_path": "lbah-code",
                }
            )
            + "\n"
        )

    (artifact / "official-report.json").write_text(
        json.dumps({"resolved_ids": ["toy__seed_0"], "unresolved_ids": []})
    )
    (artifact / "contamination_markers.jsonl").write_text(
        json.dumps(
            {
                "instance_id": marker.instance_id,
                "leak_marker": synth,
                "synthetic_marker": synth,
                "gold_fingerprint": gold,
                "leak_line": gold,
                "issue_text": marker.issue_text,
                "leak_text": marker.leak_text,
                "leak_kind": marker.leak_kind,
            }
        )
        + "\n"
    )

    # Synthetic present → flag (gold line may or may not also appear).
    _write_pred(f"@@\n-    return x - 1\n+    return x + 1  # {synth}\n")
    plan = plan_contamination_probe_on_artifacts(artifact)
    rows = run_contamination_probe_on_artifacts(plan)
    assert rows[0].flagged is True
    assert rows[0].synthetic_marker_in_diff is True

    # Gold line only (clean convergent fix) → do NOT flag.
    _write_pred(f"@@\n-    return x - 1\n+    {gold}\n")
    rows = run_contamination_probe_on_artifacts(plan)
    assert rows[0].flagged is False
    assert rows[0].synthetic_marker_in_diff is False
    assert rows[0].gold_fingerprint_in_diff is True

    # Both present → flag + gold overlap.
    _write_pred(f"@@\n-    return x - 1\n+    {gold}  # {synth}\n")
    rows = run_contamination_probe_on_artifacts(plan)
    assert rows[0].flagged is True
    assert rows[0].gold_fingerprint_in_diff is True
    assert rows[0].synthetic_marker_in_diff is True


def test_inject_script_cli(tmp_path: Path) -> None:
    src = tmp_path / "in.jsonl"
    src.write_text(json.dumps(_toy_instance().model_dump(mode="json")) + "\n")
    out = tmp_path / "leaked"
    proc = subprocess.run(
        [
            sys.executable,
            str(INJECT_SCRIPT),
            "--instances",
            str(src),
            "--out",
            str(out),
            "--force-retrieve",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert "1 injected" in proc.stdout
    assert (out / "instances.jsonl").exists()
    assert (out / "contamination_markers.jsonl").exists()
    manifest = json.loads((out / "inject_manifest.json").read_text())
    assert manifest["n_injected"] == 1
    assert manifest["force_retrieve"] is True
    assert manifest["primary_fingerprint"] == "synthetic_LEAK_MARKER"
    row = json.loads((out / "instances.jsonl").read_text().splitlines()[0])
    assert LEAK_REL_PATH in row["problem_statement"]
    assert row["metadata"]["contamination"]["synthetic_marker"].startswith("LEAK_MARKER:")
