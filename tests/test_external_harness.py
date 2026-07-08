"""Tests for black-box harness adapter helpers."""

from lbah.adapters.external_harness import (
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
