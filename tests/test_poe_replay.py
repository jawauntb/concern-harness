"""PoE-style replay capture tests.

The claim: capturing LLM (and coding-side tool) I/O onto the event log is
enough to replay a completed run and get the same commitments back — and to
raise loudly when the replay would diverge.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from lbah.adapters.dummy import EchoModel
from lbah.coding import (
    CodingAction,
    CodingEventLog,
    CodingHarnessRunner,
    CodingTask,
    CodingWorkspace,
    ModelCodingAgent,
    bundle_from_log,
)
from lbah.core import (
    ConcernEventLog,
    IOEnvelope,
    ReplayMismatchError,
    ReplayModelAdapter,
    TaskSpec,
    capture_llm_io,
    envelopes_from_log,
)


def _concern_log() -> ConcernEventLog:
    return ConcernEventLog(
        task=TaskSpec(task_id="poe_t1", task_type="tool_use", instruction="probe")
    )


def _toy_repo(tmp_path: Path) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "math_utils.py").write_text("def add(a, b):\n    return a - b\n")
    (tmp_path / "test_math_utils.py").write_text(
        "from math_utils import add\n\n"
        "def test_adds_numbers():\n"
        "    assert add(2, 3) == 5\n"
    )
    return tmp_path


def _coding_task(repo: Path, max_steps: int = 8) -> CodingTask:
    return CodingTask(
        task_id="poe_toy_add",
        instruction="Fix add so it returns the sum.",
        repo_path=str(repo),
        test_commands=[[sys.executable, "-m", "pytest", "-q"]],
        allowed_paths=["math_utils.py", "test_math_utils.py"],
        success_criteria=["pytest passes"],
        known_risks=["Do not weaken tests."],
        max_steps=max_steps,
    )


def _echo_actions() -> list[dict]:
    return [
        {"content": json.dumps({"action_type": "read_file", "payload": {"path": "math_utils.py"}})},
        {
            "content": json.dumps(
                {
                    "action_type": "edit_file",
                    "payload": {
                        "path": "math_utils.py",
                        "old": "return a - b",
                        "new": "return a + b",
                    },
                    "rationale": "Fix operator.",
                    "concerns_addressed": ["task", "risk_0"],
                }
            )
        },
        {"content": json.dumps({"action_type": "run_tests"})},
        {"content": json.dumps({"action_type": "finish"})},
    ]


class QueueModel:
    """Deterministic model that pops pre-canned responses in order."""

    def __init__(self, responses: list[dict], name: str = "queue_model"):
        self.name = name
        self.responses = list(responses)
        self.calls: list[dict] = []
        self.last_tokens = 0

    def complete(
        self,
        messages,
        *,
        schema=None,
        tools=None,
        temperature: float = 0.0,
        max_tokens=None,
    ) -> dict:
        self.calls.append({"messages": messages, "schema": schema})
        return self.responses.pop(0)


# ---------------------------------------------------------------------------
# 1. capture_llm_io round-trip on the base log
# ---------------------------------------------------------------------------


def test_replay_llm_io_roundtrip():
    log = _concern_log()
    echo = EchoModel(canned={"content": '{"ok": true}'})
    wrapper = capture_llm_io(echo, log)

    r1 = wrapper.complete([{"role": "user", "content": "one"}])
    r2 = wrapper.complete(
        [{"role": "user", "content": "two"}], schema={"type": "object"}
    )

    envelopes = envelopes_from_log(log)
    assert [e.call_index for e in envelopes] == [0, 1]
    assert envelopes[0].response == r1
    assert envelopes[1].response == r2

    replay = ReplayModelAdapter(envelopes)
    assert replay.complete([{"role": "user", "content": "one"}]) == r1
    assert replay.complete(
        [{"role": "user", "content": "two"}], schema={"type": "object"}
    ) == r2


def test_replay_mismatch_raises():
    log = _concern_log()
    wrapper = capture_llm_io(EchoModel(canned={"content": "ok"}), log)
    wrapper.complete([{"role": "user", "content": "one"}])

    envelopes = envelopes_from_log(log)
    envelopes[0].request["messages"] = [{"role": "user", "content": "TAMPERED"}]

    replay = ReplayModelAdapter(envelopes)
    with pytest.raises(ReplayMismatchError) as excinfo:
        replay.complete([{"role": "user", "content": "one"}])
    assert "TAMPERED" in excinfo.value.diff
    assert excinfo.value.call_index == 0


def test_replay_raises_when_exhausted():
    log = _concern_log()
    wrapper = capture_llm_io(EchoModel(canned={"content": "ok"}), log)
    wrapper.complete([{"role": "user", "content": "one"}])
    envelopes = envelopes_from_log(log)
    replay = ReplayModelAdapter(envelopes)
    replay.complete([{"role": "user", "content": "one"}])
    with pytest.raises(ReplayMismatchError):
        replay.complete([{"role": "user", "content": "one"}])


# ---------------------------------------------------------------------------
# 2. Coding runner: capture is off by default, on when requested
# ---------------------------------------------------------------------------


def test_coding_runner_capture_off_by_default(tmp_path: Path):
    repo = _toy_repo(tmp_path)
    task = _coding_task(repo)
    model = QueueModel(_echo_actions())
    agent = ModelCodingAgent(model)

    result = CodingHarnessRunner(agent, CodingWorkspace(repo, task)).run(task)
    assert result.success

    io_events = [e for e in result.event_log["events"] if e["type"] in {"record_llm_io", "record_tool_io"}]
    assert io_events == []


def test_coding_runner_capture_records_envelopes(tmp_path: Path):
    repo = _toy_repo(tmp_path)
    task = _coding_task(repo)
    model = QueueModel(_echo_actions())
    agent = ModelCodingAgent(model)

    result = CodingHarnessRunner(
        agent, CodingWorkspace(repo, task), capture_io=True
    ).run(task)
    assert result.success

    llm_events = [e for e in result.event_log["events"] if e["type"] == "record_llm_io"]
    tool_events = [e for e in result.event_log["events"] if e["type"] == "record_tool_io"]
    # 4 model calls, 4 executed actions (read/edit/tests/finish).
    assert len(llm_events) == 4
    assert len(tool_events) == 4
    # Envelopes are ordered by call_index in the payload.
    assert [ev["payload"]["call_index"] for ev in llm_events] == [0, 1, 2, 3]
    # After the run, the wrapped model has been unwrapped.
    assert agent.model is model


# ---------------------------------------------------------------------------
# 3. Projection is invariant to IO events
# ---------------------------------------------------------------------------


def test_projection_ignores_io_events(tmp_path: Path):
    repo = _toy_repo(tmp_path)
    task = _coding_task(repo)
    agent_plain = ModelCodingAgent(QueueModel(_echo_actions()))
    agent_captured = ModelCodingAgent(QueueModel(_echo_actions()))

    plain = CodingHarnessRunner(agent_plain, CodingWorkspace(repo, task)).run(task)
    # Reset repo for the second run.
    (repo / "math_utils.py").write_text("def add(a, b):\n    return a - b\n")
    captured = CodingHarnessRunner(
        agent_captured, CodingWorkspace(repo, task), capture_io=True
    ).run(task)

    plain_log = CodingEventLog.model_validate(plain.event_log)
    captured_log = CodingEventLog.model_validate(captured.event_log)
    plain_projection = plain_log.project().model_dump()
    captured_projection = captured_log.project().model_dump()
    plain_projection.pop("events", None)
    captured_projection.pop("events", None)
    assert plain_projection == captured_projection

    # And a concern-log projection is unchanged when record_llm_io events are added.
    log = _concern_log()
    log.append(
        "declare_variable",
        variable_id="a",
        payload={"name": "A", "concern": 0.9, "source": "task", "value": "x"},
    )
    before = log.project().model_dump()
    log.append(
        "record_llm_io",
        payload=IOEnvelope(call_index=0, request={}, response={}).model_dump(),
        source="test",
    )
    after = log.project().model_dump()
    before.pop("updates", None)
    after.pop("updates", None)
    assert before == after


# ---------------------------------------------------------------------------
# 4. End-to-end coding replay via bundle_from_log
# ---------------------------------------------------------------------------


def test_bundle_from_log_replays_llm_and_tool_streams(tmp_path: Path):
    """A completed run's log yields a bundle whose streams match the captured run.

    The replay contract is envelope-identity: given the same requests as the
    original run, the bundle emits the same responses; given the same actions,
    the tool executor emits the same observations, byte-for-byte.
    """
    repo = _toy_repo(tmp_path)
    task = _coding_task(repo)
    model = QueueModel(_echo_actions())
    agent = ModelCodingAgent(model)
    result = CodingHarnessRunner(
        agent, CodingWorkspace(repo, task), capture_io=True
    ).run(task)

    log = CodingEventLog.model_validate(result.event_log)
    bundle = bundle_from_log(log)
    assert bundle.llm_envelopes == 4
    assert bundle.tool_envelopes == 4

    # Feed the captured requests back and confirm byte-identical responses.
    llm_events = [e for e in log.events if e.type == "record_llm_io"]
    tool_events = [e for e in log.events if e.type == "record_tool_io"]

    for event in llm_events:
        request = event.payload["request"]
        expected_response = event.payload["response"]
        assert (
            bundle.model.complete(
                request["messages"],
                schema=request.get("schema"),
                tools=request.get("tools"),
                temperature=request.get("temperature") or 0.0,
                max_tokens=request.get("max_tokens"),
            )
            == expected_response
        )

    # Feed the captured actions back and confirm byte-identical observations.
    for event in tool_events:
        action = CodingAction.model_validate(event.payload["action"])
        expected_obs = event.payload["observation"]
        assert bundle.tool_executor.execute(action).model_dump() == expected_obs


def test_bundle_replay_tool_mismatch_raises(tmp_path: Path):
    repo = _toy_repo(tmp_path)
    task = _coding_task(repo)
    model = QueueModel(_echo_actions())
    agent = ModelCodingAgent(model)
    result = CodingHarnessRunner(
        agent, CodingWorkspace(repo, task), capture_io=True
    ).run(task)
    bundle = bundle_from_log(CodingEventLog.model_validate(result.event_log))

    with pytest.raises(ReplayMismatchError):
        bundle.tool_executor.execute(
            CodingAction(action_id="wrong", action_type="finish")
        )
