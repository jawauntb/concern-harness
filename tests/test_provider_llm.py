from __future__ import annotations

from typing import Any, cast

from lbah.adapters.provider_llm import ProviderLLMAdapter


class _FakeBlock:
    type = "text"
    text = "{}"


class _FakeResponse:
    content = [_FakeBlock()]
    usage = None


class _FakeMessages:
    def __init__(self):
        self.requests: list[dict] = []

    def create(self, **kwargs):
        self.requests.append(dict(kwargs))
        if "temperature" in kwargs:
            raise RuntimeError("`temperature` is deprecated for this model.")
        return _FakeResponse()


class _FakeClient:
    def __init__(self):
        self.messages = _FakeMessages()


def test_provider_llm_retries_without_deprecated_temperature():
    adapter = ProviderLLMAdapter(name="provider", api_key="test", model="claude-opus-4-8")
    fake = _FakeClient()
    adapter._client = cast(Any, fake)

    payload = adapter.complete([{"role": "user", "content": "hi"}])

    assert payload["choices"][0]["message"]["content"] == "{}"
    assert "temperature" in fake.messages.requests[0]
    assert "temperature" not in fake.messages.requests[1]
