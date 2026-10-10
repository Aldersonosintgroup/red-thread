import asyncio
import json

import httpx
import pytest

from app.services import ollama_client
from app.services.case_analysis import normalize_report, _strip_fences
from app.services.ollama_client import VisionProviderError, openai_compatible_chat


def _mock_http(monkeypatch, handler):
    """Route every httpx.AsyncClient the provider code opens to handler."""
    real = httpx.AsyncClient
    seen: list[httpx.Request] = []

    def recording(request):
        seen.append(request)
        return handler(request)

    monkeypatch.setattr(ollama_client.httpx, "AsyncClient",
                        lambda **kw: real(transport=httpx.MockTransport(recording), **kw))
    return seen


def _reply(content, model="grok-4"):
    return httpx.Response(200, json={"model": model, "choices": [{"message": {"content": content}}]})


def test_grok_goes_to_xai_with_its_own_key(monkeypatch):
    monkeypatch.setattr(ollama_client.settings, "xai_api_key", "xai-test")
    monkeypatch.setattr(ollama_client.settings, "xai_model", "grok-4")
    seen = _mock_http(monkeypatch, lambda r: _reply('{"ok": true}'))
    text, model = asyncio.run(openai_compatible_chat("grok", [{"role": "user", "content": "hi"}], {"type": "object"}, 10))
    assert (text, model) == ('{"ok": true}', "grok-4")
    assert str(seen[0].url) == "https://api.x.ai/v1/chat/completions"
    assert seen[0].headers["authorization"] == "Bearer xai-test"
    assert json.loads(seen[0].content)["response_format"]["type"] == "json_schema"


def test_service_without_schema_support_falls_back_to_plain_json(monkeypatch):
    monkeypatch.setattr(ollama_client.settings, "custom_base_url", "https://example.test/v1/")
    monkeypatch.setattr(ollama_client.settings, "custom_model", "some-model")
    monkeypatch.setattr(ollama_client.settings, "custom_api_key", "")

    def handler(request):
        fmt = json.loads(request.content).get("response_format", {}).get("type")
        return httpx.Response(400) if fmt == "json_schema" else _reply("{}", "some-model")

    seen = _mock_http(monkeypatch, handler)
    asyncio.run(openai_compatible_chat("custom", [], {"type": "object"}, 10))
    assert [json.loads(r.content).get("response_format", {}).get("type") for r in seen] == ["json_schema", "json_object"]
    assert str(seen[0].url) == "https://example.test/v1/chat/completions"
    assert "authorization" not in seen[0].headers  # local servers need no key


@pytest.mark.parametrize("status, phrase", [(401, "rejected the API key"), (404, "no model named"), (429, "limit")])
def test_errors_are_explained(monkeypatch, status, phrase):
    monkeypatch.setattr(ollama_client.settings, "openai_api_key", "k")
    _mock_http(monkeypatch, lambda r: httpx.Response(status))
    with pytest.raises(VisionProviderError, match=phrase):
        asyncio.run(openai_compatible_chat("openai", [], None, 10))


def test_custom_provider_needs_an_address(monkeypatch):
    monkeypatch.setattr(ollama_client.settings, "custom_base_url", "")
    with pytest.raises(VisionProviderError, match="address"):
        asyncio.run(openai_compatible_chat("custom", [], None, 10))


def test_loose_report_is_normalized_to_the_schema():
    raw = {
        "summary": "S",
        "established_facts": ["bare string fact", {"statement": "cited", "sources": ["D1", None]}],
        "hypotheses": [{"title": "H", "confidence": "Medium", "supporting_evidence": [{"statement": "x"}]}, {"no": "title"}],
        "next_steps": "not a list",
    }
    report = normalize_report(raw)
    assert report["established_facts"] == [{"statement": "bare string fact", "sources": []},
                                           {"statement": "cited", "sources": ["D1"]}]
    assert len(report["hypotheses"]) == 1
    h = report["hypotheses"][0]
    assert h["confidence"] == "low" and h["supporting_evidence"] == [{"statement": "x", "sources": []}]
    assert h["would_confirm"] == [] and report["next_steps"] == [] and report["gaps"] == []


def test_code_fences_are_stripped():
    assert json.loads(_strip_fences('```json\n{"a": 1}\n```')) == {"a": 1}
    assert json.loads(_strip_fences('{"a": 1}')) == {"a": 1}
