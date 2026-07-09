"""Tests for black-box harness adapter helpers."""

from lbah.adapters.external_harness import (
    OpenAICompatibleHarnessAdapter,
    extract_first_json_object,
    normalize_action_dict,
)


def test_extract_first_json_object_from_fenced_response():
    data = extract_first_json_object(
        """Here is the action:

```json
{"action_id": "a1", "payload": {"value": "x"}}
```
"""
    )
    assert data["action_id"] == "a1"
    assert data["payload"]["value"] == "x"


def test_normalize_action_dict_fills_lbah_fields():
    ledger = {
        "task": {"metadata": {"expected_action_type": "calendar.create"}},
        "surfaces": [{"id": "tool_call", "type": "tool_call"}],
    }
    normalized = normalize_action_dict({"date": "2026-07-08"}, ledger)
    assert normalized["action_id"] == "external_action"
    assert normalized["surface_id"] == "tool_call"
    assert normalized["action_type"] == "calendar.create"
    assert normalized["payload"] == {"date": "2026-07-08"}


def test_openai_compatible_complete_normalizes_choices(monkeypatch):
    adapter = OpenAICompatibleHarnessAdapter(
        name="or",
        base_url="https://example.test",
        model="anthropic/claude-opus-4.8",
        api_key="sk-test",
    )

    def fake_post(body):
        assert body["model"] == "anthropic/claude-opus-4.8"
        assert body["messages"][0]["role"] == "system"
        adapter.last_tokens = 12
        return {
            "choices": [{"message": {"content": '{"action_type":"finish"}'}}],
            "usage": {"total_tokens": 12},
        }

    monkeypatch.setattr(adapter, "_post", fake_post)
    out = adapter.complete([{"role": "user", "content": "hi"}])
    assert out["choices"][0]["message"]["content"] == '{"action_type":"finish"}'
    assert adapter.last_tokens == 12
