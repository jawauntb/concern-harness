"""Head-to-head arm surfaces + contamination gate + Track C perturbation."""

from __future__ import annotations

from pathlib import Path

from lbah.coding.actions import CodingAction, CodingTask
from lbah.coding.agents import MODEL_CODING_SYSTEM_PROMPT, RAW_CODING_SYSTEM_PROMPT
from lbah.coding.runner import CodingHarnessRunner, _synthetic_contamination_marker
from lbah.coding.workspace import CodingWorkspace
from lbah.coding.agents import ScriptedCodingAgent


def _toy_task(tmp_path: Path, *, marker: str | None = None, name: str = "repo") -> CodingTask:
    repo = tmp_path / name
    repo.mkdir(exist_ok=True)
    (repo / "math_utils.py").write_text("def add(a, b):\n    return a - b\n")
    meta = {}
    if marker:
        meta["contamination"] = {
            "synthetic_marker": marker,
            "leak_marker": marker,
        }
    return CodingTask(
        task_id="toy",
        instruction="fix add",
        repo_path=str(repo),
        allowed_paths=["math_utils.py"],
        max_steps=4,
        metadata=meta,
    )


def test_raw_prompt_differs_from_lbah() -> None:
    assert "ledger" in MODEL_CODING_SYSTEM_PROMPT.lower()
    assert "ledger" not in RAW_CODING_SYSTEM_PROMPT.lower()
    assert "typed actions" in RAW_CODING_SYSTEM_PROMPT.lower()


def test_synthetic_marker_from_metadata(tmp_path: Path) -> None:
    task = _toy_task(tmp_path, marker="LEAK_MARKER:toy", name="with_marker")
    assert _synthetic_contamination_marker(task) == "LEAK_MARKER:toy"
    assert _synthetic_contamination_marker(_toy_task(tmp_path, name="clean")) is None


class AlwaysPass:
    def verify(self, workspace, ledger):
        from lbah.coding.verifier import CodingCheckResult

        return [
            CodingCheckResult(
                name="always",
                passed=True,
                reason="ok",
                weight=1.0,
            )
        ]


def test_contamination_gate_blocks_marker_in_diff(tmp_path: Path) -> None:
    marker = "LEAK_MARKER:toy"
    task = _toy_task(tmp_path, marker=marker)
    agent = ScriptedCodingAgent(
        [
            CodingAction(
                action_id="e1",
                action_type="edit_file",
                payload={
                    "path": "math_utils.py",
                    "old": "return a - b",
                    "new": f"return a + b  # {marker}",
                },
            ),
            CodingAction(action_id="f1", action_type="finish", payload={}),
            CodingAction(
                action_id="e2",
                action_type="edit_file",
                payload={
                    "path": "math_utils.py",
                    "old": f"return a + b  # {marker}",
                    "new": "return a + b",
                },
            ),
            CodingAction(action_id="f2", action_type="finish", payload={}),
        ]
    )
    runner = CodingHarnessRunner(
        agent,
        CodingWorkspace(task.repo_path, task),
        verifier=AlwaysPass(),  # type: ignore[arg-type]
        contamination_gate=True,
    )
    result = runner.run(task)
    assert result.success is True
    assert marker not in result.final_diff
    # First finish was blocked; second finish after removing marker succeeded.
    finish_msgs = [
        step["observation"]["message"]
        for step in result.trace
        if step["action"]["action_type"] == "finish"
    ]
    assert any("contamination gate" in m for m in finish_msgs)


def test_contamination_gate_fail_closed_empties_diff_at_budget(tmp_path: Path) -> None:
    """If the marker remains when steps run out, submit an empty patch."""

    marker = "LEAK_MARKER:toy"
    task = _toy_task(tmp_path, marker=marker, name="fail_closed")
    task.max_steps = 2
    agent = ScriptedCodingAgent(
        [
            CodingAction(
                action_id="e1",
                action_type="edit_file",
                payload={
                    "path": "math_utils.py",
                    "old": "return a - b",
                    "new": f"return a + b  # {marker}",
                },
            ),
            CodingAction(action_id="f1", action_type="finish", payload={}),
            # No revise within budget — old behavior would leak the marker.
        ]
    )
    runner = CodingHarnessRunner(
        agent,
        CodingWorkspace(task.repo_path, task),
        verifier=AlwaysPass(),  # type: ignore[arg-type]
        contamination_gate=True,
    )
    result = runner.run(task)
    assert result.success is False
    assert result.final_diff == ""
    assert marker not in result.final_diff
    assert (Path(task.repo_path) / "math_utils.py").read_text() == (
        "def add(a, b):\n    return a - b\n"
    )
    assert any(
        c.name == "contamination_gate_fail_closed" and not c.passed for c in result.checks
    )


def test_restore_baseline_wipes_edits(tmp_path: Path) -> None:
    task = _toy_task(tmp_path, name="restore")
    workspace = CodingWorkspace(task.repo_path, task)
    workspace.edit_file("math_utils.py", old="return a - b", new="return a + b")
    assert workspace.diff()
    restored = workspace.restore_baseline()
    assert "math_utils.py" in restored
    assert workspace.diff() == ""


def test_perturb_replaces_leak_marker() -> None:
    import importlib.util

    path = Path(__file__).resolve().parents[1] / "scripts" / "run_two_way_gauge.py"
    spec = importlib.util.spec_from_file_location("run_two_way_gauge", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    row = {
        "instance_id": "x",
        "problem_statement": "consult LEAK_MARKER:x",
        "metadata": {
            "contamination": {
                "leak_marker": "LEAK_MARKER:x",
                "synthetic_marker": "LEAK_MARKER:x",
                "leak_text": "LEAK_MARKER:x in carrier",
            }
        },
    }
    out = mod._perturb_instance(row)
    assert "ALT_LEAK:x" in out["problem_statement"]
    assert out["metadata"]["contamination"]["leak_marker"] == "ALT_LEAK:x"
    assert "LEAK_MARKER:" not in out["metadata"]["contamination"]["leak_text"]
