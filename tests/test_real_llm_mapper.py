"""Real-LLM concern mapper wiring: `.complete()` on ClaudeCodeCLIAdapter.

These are wiring tests (no real Claude calls) — the actual `claude -p` eval
lives under `scripts/concern_mapper_eval.py --model claude`.
"""

from __future__ import annotations

import json
from unittest import mock

from lbah.adapters.claude_code_llm import ClaudeCodeCLIAdapter
from lbah.benches import load_suite
from lbah.core.schemas import State
from lbah.modules.concern_mapper import LLMConcernMapper


def _fake_process(stdout: str, returncode: int = 0):
    result = mock.MagicMock()
    result.stdout = stdout
    result.stderr = ""
    result.returncode = returncode
    return result


def test_claude_adapter_complete_wraps_response_in_choices_shape():
    payload = json.dumps({"concern_variables": []})
    with mock.patch(
        "lbah.adapters.claude_code_llm.subprocess.run",
        return_value=_fake_process(payload),
    ):
        adapter = ClaudeCodeCLIAdapter(name="probe", timeout=5.0)
        resp = adapter.complete(
            [
                {"role": "system", "content": "you are the concern mapper"},
                {"role": "user", "content": "task json"},
            ]
        )
    assert resp["choices"][0]["message"]["content"] == payload


def test_claude_adapter_complete_extracts_system_prompt_from_messages():
    payload = json.dumps({"concern_variables": []})
    captured: dict = {}

    def spy(cmd, **kwargs):
        captured["cmd"] = cmd
        return _fake_process(payload)

    with mock.patch("lbah.adapters.claude_code_llm.subprocess.run", side_effect=spy):
        adapter = ClaudeCodeCLIAdapter(name="probe", timeout=5.0)
        adapter.complete(
            [
                {"role": "system", "content": "concern mapper system"},
                {"role": "user", "content": "task json"},
            ]
        )
    cmd = captured["cmd"]
    assert "--append-system-prompt" in cmd
    idx = cmd.index("--append-system-prompt")
    assert cmd[idx + 1] == "concern mapper system"


def test_llm_mapper_end_to_end_with_claude_adapter_mock():
    """LLMConcernMapper + ClaudeCodeCLIAdapter path returns parsed variables."""
    payload = json.dumps(
        {
            "concern_variables": [
                {
                    "id": "slot_D",
                    "name": "field D",
                    "value": "xml",
                    "concern": 1.0,
                    "source": "task.instruction",
                    "required_surfaces": ["tool_call"],
                    "proxy_risks": ["uses first slot"],
                }
            ]
        }
    )
    with mock.patch(
        "lbah.adapters.claude_code_llm.subprocess.run",
        return_value=_fake_process(payload),
    ):
        adapter = ClaudeCodeCLIAdapter(name="probe", timeout=5.0)
        mapper = LLMConcernMapper(adapter, prefer_metadata=False)
        suite = load_suite("moved_bottleneck")
        task = suite.generate(0)
        meta = dict(task.metadata or {})
        meta.pop("concern_variables", None)
        task = task.model_copy(update={"metadata": meta})
        variables = mapper.extract(task, State(task_id=task.task_id))
    assert len(variables) == 1
    assert variables[0].value == "xml"
    assert variables[0].concern == 1.0


def test_claude_adapter_complete_returns_error_shape_on_nonzero_exit():
    """A failing claude call surfaces the stderr JSON — no silent crash."""
    with mock.patch(
        "lbah.adapters.claude_code_llm.subprocess.run",
        return_value=_fake_process("", returncode=1),
    ):
        adapter = ClaudeCodeCLIAdapter(name="probe", timeout=5.0)
        resp = adapter.complete([{"role": "user", "content": "hi"}])
    text = resp["choices"][0]["message"]["content"]
    assert "claude_error" in text or "returncode" in text
