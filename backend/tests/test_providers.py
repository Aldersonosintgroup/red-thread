import asyncio
import json

import pytest

from app.core import config
from app.services import ollama_client
from app.services.ollama_client import ProviderResponse, VisionProviderError, provider_order
from app.services.vision_extraction import EXTRACTION_SCHEMA, _to_result


@pytest.mark.parametrize("chosen, expected", [
    ("ollama", ["ollama"]),            # local stays local: never escalates to the cloud
    ("claude", ["claude", "ollama"]),  # cloud falls back only to the local engine
    ("gemini", ["gemini", "ollama"]),
    ("openai", ["openai", "ollama"]),
    ("grok", ["grok", "ollama"]),
    ("custom", ["custom", "ollama"]),
    ("bogus", ["ollama"]),
])
def test_fallback_never_reaches_an_unchosen_cloud_provider(chosen, expected):
    assert provider_order(chosen) == expected


def test_all_failures_are_reported_together(monkeypatch):
    async def fail_claude(*_):
        raise VisionProviderError("Claude rejected the API key.")

    async def fail_ollama(*_):
        raise VisionProviderError("Local AI engine request failed")

    async def must_not_run(*_):
        raise AssertionError("an unchosen cloud provider was called")

    monkeypatch.setattr(ollama_client.settings, "ai_provider", "claude")
    monkeypatch.setitem(ollama_client.PROVIDERS, "claude", fail_claude)
    monkeypatch.setitem(ollama_client.PROVIDERS, "ollama", fail_ollama)
    monkeypatch.setitem(ollama_client.PROVIDERS, "gemini", must_not_run)
    monkeypatch.setitem(ollama_client.PROVIDERS, "openai", must_not_run)
    monkeypatch.setitem(ollama_client.PROVIDERS, "grok", must_not_run)
    monkeypatch.setitem(ollama_client.PROVIDERS, "custom", must_not_run)

    with pytest.raises(VisionProviderError) as exc:
        asyncio.run(ollama_client.run_vision_extraction(b"img", "prompt", "image/jpeg", {}))
    assert "Claude rejected" in str(exc.value) and "Local AI engine" in str(exc.value)


def test_successful_provider_is_recorded(monkeypatch):
    async def claude_ok(*_):
        return ProviderResponse(text="{}", extracted_by="claude:claude-opus-5-5")

    monkeypatch.setattr(ollama_client.settings, "ai_provider", "claude")
    monkeypatch.setitem(ollama_client.PROVIDERS, "claude", claude_ok)
    result = asyncio.run(ollama_client.run_vision_extraction(b"img", "p", "image/jpeg", {}))
    assert result.extracted_by == "claude:claude-opus-5-5"


def _walk_objects(schema):
    if isinstance(schema, dict):
        if schema.get("type") == "object":
            yield schema
        for value in schema.values():
            yield from _walk_objects(value)
    elif isinstance(schema, list):
        for value in schema:
            yield from _walk_objects(value)


def test_schema_meets_structured_output_rules():
    # Claude's structured outputs require additionalProperties: false and
    # every property listed as required, on every object.
    for obj in _walk_objects(EXTRACTION_SCHEMA):
        assert obj.get("additionalProperties") is False
        assert set(obj["required"]) == set(obj["properties"])


def test_schema_shaped_response_converts_and_keeps_dates_as_written():
    response = json.dumps({
        "doc_type": "correspondence",
        "names": [{"name": "John Example", "role": "Recipient"}],
        "dates": [{"label": "document_date", "date": "June 3, 1985"}],
        "financial_transactions": [],
        "legal_references": [],
        "raw_text_notes": "Letter to an official about adoption delays.",
    })
    result = _to_result(response)
    assert result.doc_type == "correspondence"
    assert result.names[0].name == "John Example"
    assert result.dates == [{"label": "document_date", "date": "June 3, 1985"}]
    assert result.parse_warning is None


def test_blank_saved_model_name_does_not_override_default(tmp_path, monkeypatch):
    settings_file = tmp_path / "app_settings.json"
    settings_file.write_text(json.dumps({"ai_provider": "claude", "claude_vision_model": ""}), encoding="utf-8")
    monkeypatch.setattr(config, "SETTINGS_FILE", settings_file)
    loaded = config._load_settings()
    assert loaded.ai_provider == "claude"
    assert loaded.claude_vision_model == config.Settings().claude_vision_model != ""
