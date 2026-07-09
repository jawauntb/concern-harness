"""Phase 1: coding event log, finish certificates, tool-failure gates."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from click.testing import CliRunner

from lbah.cli import cli
from lbah.coding import (
    CandidatePatchTournamentRunner,
    CodingAction,
    CodingEventLog,
    CodingHarnessRunner,
    CodingLedger,
    CodingTask,
    CodingWorkspace,
    ScriptedCodingAgent,
    events_from_ledger,
)
from lbah.coding.certificates import make_finish_certificate
from lbah.validators import tool_validators
from lbah.core.schemas import ActionProposal, ConcernLedger, ConcernVariable, CommitmentSurface, State, TaskSpec


def _toy_repo(tmp_path: Path) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "math_utils.py").write_text("def add(a, b):\n    return a - b\n")
    (tmp_path / "test_math_utils.py").write_text(
        "from math_utils import add\n\n"
        "def test_adds_numbers():\n"
        "    assert add(2, 3) == 5\n"
    )
    return tmp_path


def _task(repo: Path, max_steps: int = 8) -> CodingTask:
    return CodingTask(
        task_id="toy_add",
        instruction="Fix add so it returns the sum.",
        repo_path=str(repo),
        test_commands=[[sys.executable, "-m", "pytest", "-q"]],
        allowed_paths=["math_utils.py", "test_math_utils.py"],
        success_criteria=["pytest passes"],
        known_risks=["Do not weaken tests."],
        max_steps=max_steps,
    )


def test_coding_event_log_projection_preserves_unresolved():
    task = CodingTask(task_id="t", instruction="x", success_criteria=["a"], known_risks=["r"])
    ledger = CodingLedger.from_task(task)
    log = events_from_ledger(ledger)
    projected = log.project()
    assert [c.id for c in projected.concerns] == [c.id for c in ledger.concerns]
    assert {c.id for c in projected.unresolved()} == {c.id for c in ledger.unresolved()}


def test_coding_event_log_lineage_and_fork():
    task = CodingTask(task_id="t", instruction="x")
    ledger = CodingLedger.from_task(task)
    log = events_from_ledger(ledger)
    log.append("set_status", concern_id="task", payload={"status": "addressed"}, source="test")
    lineage = log.lineage("task")
    assert lineage
    assert lineage[-1].type == "set_status"
    branch = log.fork_at(lineage[0].seq, label="cand")
    assert branch.label == "cand"
    assert branch.forked_from == "root"


def test_coding_runner_emits_certificate_and_event_log(tmp_path: Path):
    repo = _toy_repo(tmp_path)
    task = _task(repo)
    agent = ScriptedCodingAgent(
        [
            CodingAction(action_id="read", action_type="read_file", payload={"path": "math_utils.py"}),
            CodingAction(
                action_id="edit",
                action_type="edit_file",
                payload={"path": "math_utils.py", "old": "return a - b", "new": "return a + b"},
                rationale="fix subtract",
                concerns_addressed=["task", "risk_0"],
            ),
            CodingAction(action_id="tests", action_type="run_tests"),
            CodingAction(action_id="finish", action_type="finish"),
        ]
    )
    result = CodingHarnessRunner(agent, CodingWorkspace(repo, task)).run(task)
    assert result.success
    assert result.certificates
    cert = result.certificates[0]
    assert cert.transport_results
    assert cert.proxy_results
    assert any(r.gate_name.startswith("validator::") for r in cert.validator_results)
    # ToolFailBench-named gates present.
    names = {r.gate_name for r in cert.transport_results + cert.proxy_results + cert.validator_results}
    assert "transport::result_ignore" in names
    assert "proxy::output_fabrication" in names
    assert "validator::tool_skip" in names
    assert result.event_log is not None
    log = CodingEventLog.model_validate(result.event_log)
    assert log.lineage("task")
    assert log.project().unresolved() is not None


def test_cli_replay_lineage_on_coding_run(tmp_path: Path):
    repo = _toy_repo(tmp_path / "repo")
    task = _task(repo)
    agent = ScriptedCodingAgent(
        [
            CodingAction(
                action_id="edit",
                action_type="edit_file",
                payload={"path": "math_utils.py", "old": "return a - b", "new": "return a + b"},
                concerns_addressed=["task"],
            ),
            CodingAction(action_id="tests", action_type="run_tests"),
            CodingAction(action_id="finish", action_type="finish"),
        ]
    )
    result = CodingHarnessRunner(agent, CodingWorkspace(repo, task)).run(task)
    out = tmp_path / "out"
    out.mkdir()
    run_path = out / "coding_run.json"
    run_path.write_text(result.model_dump_json(indent=2))

    runner = CliRunner()
    replayed = runner.invoke(cli, ["replay", str(run_path), "--lineage", "task"])
    assert replayed.exit_code == 0, replayed.output
    assert "Lineage of 'task'" in replayed.output


def test_tournament_records_fork_lineage(tmp_path: Path):
    repo = _toy_repo(tmp_path)
    task = _task(repo)
    good = ScriptedCodingAgent(
        [
            CodingAction(
                action_id="edit",
                action_type="edit_file",
                payload={"path": "math_utils.py", "old": "return a - b", "new": "return a + b"},
                rationale="fix subtract",
                concerns_addressed=["task", "risk_0"],
            ),
            CodingAction(action_id="tests", action_type="run_tests"),
            CodingAction(action_id="finish", action_type="finish"),
        ],
        name="good",
    )
    bad = ScriptedCodingAgent(
        [CodingAction(action_id="finish", action_type="finish")],
        name="bad",
    )
    result = CandidatePatchTournamentRunner(
        [bad, good], CodingWorkspace(repo, task)
    ).run(task)
    assert result.success
    assert result.event_log is not None
    root = CodingEventLog.model_validate(result.event_log)
    assert any(e.type == "note" and e.payload.get("kind") == "winner_selected" for e in root.events)
    winner = next(c for c in result.candidates if c.selected)
    assert winner.event_log is not None
    branch = CodingEventLog.model_validate(winner.event_log)
    assert branch.label.startswith("candidate_")
    assert any(e.type == "fork_workspace" for e in branch.events)


def test_tool_failure_validators_registered():
    task = TaskSpec(task_id="t", task_type="coding", instruction="x")
    ledger = ConcernLedger(
        task=task,
        variables=[ConcernVariable(id="v", name="v", concern=0.9, source="task", value="x")],
        surfaces=[CommitmentSurface(id="code_diff", name="d", type="code_diff")],
    )
    proposal = ActionProposal(action_id="a", surface_id="code_diff", action_type="finish", payload={})
    state = State(task_id="t", scratch={"coding_trace": [], "coding_ledger": {"concerns": []}})
    assert tool_validators.result_ignore(proposal, ledger, state, None).gate_name == "transport::result_ignore"
    assert tool_validators.output_fabrication(proposal, ledger, state, None).gate_name == "proxy::output_fabrication"
    assert tool_validators.tool_skip(proposal, ledger, state, None).gate_name == "validator::tool_skip"
    assert (
        tool_validators.unnecessary_tool_use(proposal, ledger, state, None).gate_name
        == "validator::unnecessary_tool_use"
    )


def test_make_finish_certificate_includes_named_gates(tmp_path: Path):
    repo = _toy_repo(tmp_path)
    task = _task(repo)
    ledger = CodingLedger.from_task(task)
    cert = make_finish_certificate(
        task=task,
        ledger=ledger,
        checks=[],
        trace=[],
        final_diff="",
        modified_files=[],
    )
    names = {
        r.gate_name
        for r in cert.transport_results + cert.proxy_results + cert.validator_results
    }
    assert "transport::result_ignore" in names
    assert "proxy::output_fabrication" in names
