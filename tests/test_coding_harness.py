from __future__ import annotations

import json
import sys
from pathlib import Path

from click.testing import CliRunner

from lbah.cli import cli
from lbah.coding import (
    CodingAction,
    CodingHarnessRunner,
    CodingTask,
    CodingWorkspace,
    ModelCodingAgent,
    ScriptedCodingAgent,
)
from lbah.coding.agents import extract_action_json, model_response_content


class FakeModel:
    def __init__(self, responses: list[dict], name: str = "fake_model"):
        self.name = name
        self.responses = list(responses)
        self.messages: list[list[dict]] = []

    def complete(
        self,
        messages: list[dict],
        *,
        schema: dict | None = None,
        tools: list[dict] | None = None,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> dict:
        self.messages.append(messages)
        if not self.responses:
            return {"content": '{"action_type": "finish"}'}
        return self.responses.pop(0)


def _toy_repo(tmp_path: Path) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "math_utils.py").write_text(
        "def add(a, b):\n"
        "    return a - b\n"
    )
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


def test_coding_runner_solves_toy_repo(tmp_path: Path):
    repo = _toy_repo(tmp_path)
    task = _task(repo)
    agent = ScriptedCodingAgent(
        [
            CodingAction(
                action_id="read",
                action_type="read_file",
                payload={"path": "math_utils.py"},
            ),
            CodingAction(
                action_id="edit",
                action_type="edit_file",
                payload={"path": "math_utils.py", "old": "return a - b", "new": "return a + b"},
                rationale="The implementation subtracts; the task requires addition.",
                concerns_addressed=["task", "risk_0"],
            ),
            CodingAction(action_id="tests", action_type="run_tests"),
            CodingAction(action_id="finish", action_type="finish"),
        ]
    )

    result = CodingHarnessRunner(agent, CodingWorkspace(repo, task)).run(task)

    assert result.success
    assert result.modified_files == ["math_utils.py"]
    assert "return a + b" in (repo / "math_utils.py").read_text()
    assert "return a + b" in result.final_diff
    assert any(check.name == "tests_pass" and check.passed for check in result.checks)


def test_failed_finish_feeds_back_and_allows_retry(tmp_path: Path):
    repo = _toy_repo(tmp_path)
    task = _task(repo, max_steps=6)
    agent = ScriptedCodingAgent(
        [
            CodingAction(action_id="finish_early", action_type="finish"),
            CodingAction(
                action_id="edit",
                action_type="edit_file",
                payload={"path": "math_utils.py", "old": "return a - b", "new": "return a + b"},
                rationale="Verifier reported failing tests; fix the operator.",
                concerns_addressed=["task", "risk_0"],
            ),
            CodingAction(action_id="tests", action_type="run_tests"),
            CodingAction(action_id="finish", action_type="finish"),
        ]
    )

    result = CodingHarnessRunner(agent, CodingWorkspace(repo, task)).run(task)

    assert result.success
    assert result.steps == 4
    first_observation = result.trace[0]["observation"]
    assert not first_observation["success"]
    assert "verification failed" in first_observation["message"]
    assert any(
        concern["id"].startswith("verification_failure_")
        for concern in result.ledger["concerns"]
    )


def test_workspace_rejects_path_escape(tmp_path: Path):
    repo = _toy_repo(tmp_path / "repo")
    task = _task(repo)
    workspace = CodingWorkspace(repo, task)

    try:
        workspace.read_file("../outside.py")
    except ValueError as exc:
        assert "escapes workspace" in str(exc)
    else:
        raise AssertionError("expected path escape to fail")


def test_code_run_cli_writes_artifacts(tmp_path: Path):
    repo = _toy_repo(tmp_path / "repo")
    task_path = tmp_path / "task.yaml"
    actions_path = tmp_path / "actions.yaml"
    out_dir = tmp_path / "out"
    task_path.write_text(
        "task_id: toy_add\n"
        "instruction: Fix add so it returns the sum.\n"
        "test_commands:\n"
        f"  - [{json.dumps(sys.executable)}, -m, pytest, -q]\n"
        "allowed_paths: [math_utils.py]\n"
        "success_criteria: [pytest passes]\n"
        "known_risks: [Do not weaken tests.]\n"
        "max_steps: 5\n"
    )
    actions_path.write_text(
        "name: scripted\n"
        "actions:\n"
        "  - action_id: edit\n"
        "    action_type: edit_file\n"
        "    payload:\n"
        "      path: math_utils.py\n"
        "      old: return a - b\n"
        "      new: return a + b\n"
        "    rationale: Fix wrong operator.\n"
        "    concerns_addressed: [task, risk_0]\n"
        "  - action_id: tests\n"
        "    action_type: run_tests\n"
        "  - action_id: finish\n"
        "    action_type: finish\n"
    )

    result = CliRunner().invoke(
        cli,
        [
            "code",
            "run",
            "--task",
            str(task_path),
            "--repo",
            str(repo),
            "--actions",
            str(actions_path),
            "--out",
            str(out_dir),
        ],
    )

    assert result.exit_code == 0, result.output
    run = json.loads((out_dir / "coding_run.json").read_text())
    assert run["success"]
    assert (out_dir / "final.diff").read_text()


def test_extract_action_json_accepts_fenced_text():
    data = extract_action_json(
        "```json\n"
        '{"action_type": "read_file", "payload": {"path": "math_utils.py"}}\n'
        "```"
    )

    assert data["action_type"] == "read_file"
    assert data["payload"]["path"] == "math_utils.py"


def test_model_response_content_accepts_chat_shape():
    content = model_response_content(
        {"choices": [{"message": {"content": '{"action_type": "inspect"}'}}]}
    )

    assert content == '{"action_type": "inspect"}'


def test_model_response_content_accepts_content_parts():
    content = model_response_content(
        {
            "choices": [
                {
                    "message": {
                        "content": [
                            {"type": "text", "text": '{"action_type": "inspect"}'},
                        ]
                    }
                }
            ]
        }
    )

    assert content == '{"action_type": "inspect"}'


def test_model_coding_agent_solves_toy_repo(tmp_path: Path):
    repo = _toy_repo(tmp_path)
    task = _task(repo)
    model = FakeModel(
        [
            {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "action_type": "read_file",
                                    "payload": {"path": "math_utils.py"},
                                }
                            )
                        }
                    }
                ],
                "usage": {"total_tokens": 10},
            },
            {
                "content": json.dumps(
                    {
                        "action_type": "edit_file",
                        "payload": {
                            "path": "math_utils.py",
                            "old": "return a - b",
                            "new": "return a + b",
                        },
                        "rationale": "Fix the operator.",
                        "concerns_addressed": ["task", "risk_0"],
                    }
                )
            },
            {"content": '{"action_type": "run_tests"}'},
            {"content": '{"action_type": "finish"}'},
        ]
    )
    agent = ModelCodingAgent(model)

    result = CodingHarnessRunner(agent, CodingWorkspace(repo, task)).run(task)

    assert result.success
    assert result.agent == "fake_model_coding"
    assert model.messages
    assert agent.last_tokens == 0
    assert "return a + b" in (repo / "math_utils.py").read_text()


def test_model_action_parse_error_is_feedback_and_can_retry(tmp_path: Path):
    repo = _toy_repo(tmp_path)
    task = _task(repo, max_steps=6)
    model = FakeModel(
        [
            {"content": "not json"},
            {
                "content": json.dumps(
                    {
                        "action_type": "edit_file",
                        "payload": {
                            "path": "math_utils.py",
                            "old": "return a - b",
                            "new": "return a + b",
                        },
                        "rationale": "Retry after parser feedback.",
                        "concerns_addressed": ["task", "risk_0"],
                    }
                )
            },
            {"content": '{"action_type": "run_tests"}'},
            {"content": '{"action_type": "finish"}'},
        ]
    )

    result = CodingHarnessRunner(ModelCodingAgent(model), CodingWorkspace(repo, task)).run(task)

    assert result.success
    assert result.trace[0]["action"]["action_type"] == "invalid_action"
    assert "proposal_error" in result.trace[0]["observation"]["message"]
    assert "proposal_error" in model.messages[1][1]["content"]
