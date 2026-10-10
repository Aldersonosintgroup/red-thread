"""Vision provider clients. Claude is the primary (best accuracy on real,
dense documents); Ollama is the free, fully local engine bundled with the
app; Gemini, OpenAI, Grok, or any OpenAI-compatible service (OpenRouter,
DeepSeek, Mistral, a local LM Studio server...) can be chosen instead. All keys are configured
server-side only and never reach the frontend.

Two guarantees this module enforces:

* Structured output. Claude and Ollama are given the extraction JSON schema
  and constrained to it, so their responses always parse. The others are asked
  for JSON in the strictest form they accept; the caller still tolerates a
  malformed reply.
* No surprise uploads. If the chosen provider fails, the only fallback is
  the local Ollama engine. Evidence is never sent to a cloud provider the
  user didn't select.
"""
import base64
import logging
from dataclasses import dataclass

import anthropic
import httpx

from app.core.config import settings

logger = logging.getLogger("redthread.ai")

LOCAL_PROVIDER = "ollama"
CLOUD_PROVIDERS = ("claude", "gemini", "openai", "grok", "custom")


class VisionProviderError(Exception):
    pass


@dataclass
class ProviderResponse:
    text: str
    extracted_by: str  # "<provider>:<model>", recorded with the extraction for provenance


def _b64(image_bytes: bytes) -> str:
    return base64.standard_b64encode(image_bytes).decode("ascii")


async def _call_claude(image_bytes: bytes, prompt: str, media_type: str, schema: dict) -> ProviderResponse:
    if not settings.anthropic_api_key:
        raise VisionProviderError("Claude API key not configured")
    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key, timeout=180.0, max_retries=2)
    try:
        response = await client.beta.messages.create(
            model=settings.claude_vision_model,
            max_tokens=16000,
            # If a safety classifier declines a page, retry it server-side on
            # Anthropic's recommended fallback model instead of failing.
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            output_config={
                "effort": "medium",
                "format": {"type": "json_schema", "schema": schema},
            },
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": _b64(image_bytes)}},
                    {"type": "text", "text": prompt},
                ],
            }],
        )
    except anthropic.AuthenticationError as exc:
        raise VisionProviderError("Claude rejected the API key. Re-enter it in Settings.") from exc
    except anthropic.PermissionDeniedError as exc:
        raise VisionProviderError("This Claude API key isn't allowed to use this model.") from exc
    except anthropic.NotFoundError as exc:
        raise VisionProviderError(f"Claude model '{settings.claude_vision_model}' was not found.") from exc
    except anthropic.RateLimitError as exc:
        raise VisionProviderError("Claude rate limit reached. Wait a minute and re-run extraction.") from exc
    except anthropic.APIStatusError as exc:
        raise VisionProviderError(f"Claude request failed ({exc.status_code}): {exc.message}") from exc
    except anthropic.APIConnectionError as exc:
        raise VisionProviderError("Could not reach Claude. Check the internet connection.") from exc
    finally:
        await client.close()

    if response.stop_reason == "refusal":
        raise VisionProviderError("Claude declined to read this page.")
    if response.stop_reason == "max_tokens":
        raise VisionProviderError("Claude's answer for this page was cut off (too much text on one page).")
    text = next((block.text for block in response.content if block.type == "text"), "")
    return ProviderResponse(text=text, extracted_by=f"claude:{response.model}")


async def _call_ollama(image_bytes: bytes, prompt: str, media_type: str, schema: dict) -> ProviderResponse:
    model = settings.ollama_vision_model
    payload = {
        "model": model,
        "prompt": prompt,
        "images": [_b64(image_bytes)],
        "stream": False,
        "format": schema,  # constrains decoding to the extraction schema
        "options": {"temperature": 0},
        # Loading the model takes minutes on first use; keep it in memory
        # across a batch instead of Ollama's default 5-minute unload.
        "keep_alive": "30m",
    }
    try:
        async with httpx.AsyncClient(timeout=300.0) as client:
            resp = await client.post(f"{settings.ollama_host}/api/generate", json=payload)
            resp.raise_for_status()
            data = resp.json()
            # Thinking-capable models (e.g. Qwen3-VL) can return the
            # schema-constrained answer in "thinking" with an empty "response".
            text = data.get("response") or data.get("thinking") or ""
            return ProviderResponse(text=text, extracted_by=f"ollama:{model}")
    except httpx.HTTPError as exc:
        raise VisionProviderError(f"Local AI engine request failed: {exc}") from exc


async def _call_gemini(image_bytes: bytes, prompt: str, media_type: str, schema: dict) -> ProviderResponse:
    if not settings.gemini_api_key:
        raise VisionProviderError("Gemini API key not configured")
    model = settings.gemini_vision_model
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    # Key in a header, never the URL: request URLs end up in exception text
    # and logs, and from there in the document's stored error message.
    headers = {"x-goog-api-key": settings.gemini_api_key}
    payload = {
        "contents": [{"parts": [{"text": prompt}, {"inline_data": {"mime_type": media_type, "data": _b64(image_bytes)}}]}],
        "generationConfig": {"responseMimeType": "application/json", "temperature": 0},
    }
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            text = data["candidates"][0]["content"]["parts"][0]["text"]
            return ProviderResponse(text=text, extracted_by=f"gemini:{model}")
    except httpx.HTTPStatusError as exc:
        raise VisionProviderError(f"Gemini request failed ({exc.response.status_code})") from exc
    except (httpx.HTTPError, KeyError, IndexError) as exc:
        raise VisionProviderError(f"Gemini request failed: {type(exc).__name__}") from exc


async def gemini_text_json(system: str, user: str, schema: dict, timeout: float) -> tuple[str, str]:
    """Text-only Gemini call asking for JSON matching schema; returns (text, model)."""
    if not settings.gemini_api_key:
        raise VisionProviderError("Gemini API key not configured")
    model = settings.gemini_vision_model
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    headers = {"x-goog-api-key": settings.gemini_api_key}
    payload = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": user}]}],
        "generationConfig": {"responseMimeType": "application/json", "responseJsonSchema": schema},
    }
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, json=payload, headers=headers)
            if resp.status_code == 400:  # older models: plain JSON mode, schema stays in the prompt
                del payload["generationConfig"]["responseJsonSchema"]
                resp = await client.post(url, json=payload, headers=headers)
            if resp.status_code >= 400:
                raise VisionProviderError(_openai_error("Gemini", model, resp.status_code))
            data = resp.json()
            return data["candidates"][0]["content"]["parts"][0]["text"], model
    except httpx.HTTPError as exc:
        raise VisionProviderError(f"Could not reach Gemini: {type(exc).__name__}") from exc
    except (KeyError, IndexError, ValueError) as exc:
        raise VisionProviderError("Gemini sent an unexpected reply (possibly blocked by its safety filter)") from exc


# Providers that speak the OpenAI chat-completions API: name -> (label,
# key field, model field). Their base URL comes from _base_url().
OPENAI_COMPATIBLE = {
    "openai": ("OpenAI", "openai_api_key", "openai_vision_model"),
    "grok": ("Grok", "xai_api_key", "xai_model"),
    "custom": ("Custom provider", "custom_api_key", "custom_model"),
}
_BASE_URLS = {"openai": "https://api.openai.com/v1", "grok": "https://api.x.ai/v1"}


def _base_url(name: str) -> str:
    if name == "custom":
        return settings.custom_base_url.strip().rstrip("/")
    return _BASE_URLS[name]


def _openai_error(label: str, model: str, status: int) -> str:
    if status in (401, 403):
        return f"{label} rejected the API key. Re-enter it in Settings."
    if status == 404:
        return f"{label} has no model named '{model}' (or the address is wrong). Check Settings."
    if status == 429:
        return f"{label} rate limit or spending limit reached. Wait a minute and try again."
    return f"{label} request failed ({status})"


async def openai_compatible_chat(name: str, messages: list[dict], schema: dict | None, timeout: float) -> tuple[str, str]:
    """One chat-completions call; returns (text, model). Asks for JSON in
    the strictest form the service accepts: a JSON schema, then plain JSON
    mode, then nothing (the prompt still asks for JSON and the caller
    tolerates a malformed reply). Services differ in which they support."""
    label, key_field, model_field = OPENAI_COMPATIBLE[name]
    key, model, base = getattr(settings, key_field), getattr(settings, model_field), _base_url(name)
    if name == "custom" and not base.startswith(("http://", "https://")):
        raise VisionProviderError("Custom provider address not set (Settings), e.g. https://openrouter.ai/api/v1")
    if not model:
        raise VisionProviderError(f"{label} model name not set (Settings)")
    if not key and name != "custom":  # a local server may need no key
        raise VisionProviderError(f"{label} API key not configured")
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    formats: list[dict | None] = [None]
    if schema is not None:
        formats = [{"type": "json_schema", "json_schema": {"name": "result", "schema": schema}},
                   {"type": "json_object"}, None]
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            for i, response_format in enumerate(formats):
                payload: dict = {"model": model, "messages": messages}
                if response_format:
                    payload["response_format"] = response_format
                resp = await client.post(f"{base}/chat/completions", json=payload, headers=headers)
                if resp.status_code in (400, 422) and i < len(formats) - 1:
                    continue  # this service doesn't take that response format; try the next
                if resp.status_code >= 400:
                    raise VisionProviderError(_openai_error(label, model, resp.status_code))
                data = resp.json()
                return data["choices"][0]["message"]["content"] or "", data.get("model") or model
    except httpx.HTTPError as exc:
        raise VisionProviderError(f"Could not reach {label}: {type(exc).__name__}") from exc
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise VisionProviderError(f"{label} sent an unexpected reply") from exc
    raise VisionProviderError(f"{label} request failed")


def _openai_compatible_vision(name: str):
    async def call(image_bytes: bytes, prompt: str, media_type: str, schema: dict) -> ProviderResponse:
        messages = [{
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": f"data:{media_type};base64,{_b64(image_bytes)}"}},
            ],
        }]
        text, model = await openai_compatible_chat(name, messages, schema, timeout=180.0)
        return ProviderResponse(text=text, extracted_by=f"{name}:{model}")
    return call


PROVIDERS = {
    "claude": _call_claude,
    "ollama": _call_ollama,
    "gemini": _call_gemini,
    **{name: _openai_compatible_vision(name) for name in OPENAI_COMPATIBLE},
}


def provider_order(chosen: str) -> list[str]:
    """The chosen provider, then the local engine as the only fallback."""
    chosen = chosen if chosen in PROVIDERS else LOCAL_PROVIDER
    return [chosen] if chosen == LOCAL_PROVIDER else [chosen, LOCAL_PROVIDER]


async def run_vision_extraction(image_bytes: bytes, prompt: str, media_type: str, schema: dict) -> ProviderResponse:
    """Try the chosen provider, then the local engine. Raises
    VisionProviderError (with every provider's reason) if all fail."""
    errors: list[str] = []
    for name in provider_order(settings.ai_provider):
        try:
            return await PROVIDERS[name](image_bytes, prompt, media_type, schema)
        except VisionProviderError as exc:
            logger.warning("Vision provider %s failed: %s", name, exc)
            errors.append(str(exc))
    raise VisionProviderError(" / ".join(errors))


async def test_provider(name: str) -> str:
    """Check the selected provider answers, with a tiny text-only request that
    carries no case data. Returns a short description of what answered."""
    prompt = 'Reply with exactly this JSON: {"ok": true}'
    if name == "ollama":
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(f"{settings.ollama_host}/api/tags")
                resp.raise_for_status()
                names = [m.get("name", "") for m in resp.json().get("models", [])]
        except (httpx.HTTPError, ValueError) as exc:
            raise VisionProviderError("The built-in local engine isn't running. Restart Red Thread.") from exc
        if settings.ollama_vision_model not in names:
            raise VisionProviderError(f"Local engine is running but model '{settings.ollama_vision_model}' is missing.")
        return f"Local engine ready ({settings.ollama_vision_model})."
    if name == "claude":
        if not settings.anthropic_api_key:
            raise VisionProviderError("Claude API key not configured")
        client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key, timeout=60.0, max_retries=1)
        try:
            response = await client.messages.create(
                model=settings.claude_vision_model, max_tokens=50,
                messages=[{"role": "user", "content": prompt}])
        except anthropic.AuthenticationError as exc:
            raise VisionProviderError("Claude rejected the API key. Re-enter it in Settings.") from exc
        except anthropic.NotFoundError as exc:
            raise VisionProviderError(f"Claude has no model named '{settings.claude_vision_model}'.") from exc
        except anthropic.APIStatusError as exc:
            raise VisionProviderError(f"Claude request failed ({exc.status_code}): {exc.message}") from exc
        except anthropic.APIConnectionError as exc:
            raise VisionProviderError("Could not reach Claude. Check the internet connection.") from exc
        finally:
            await client.close()
        return f"Claude answered ({response.model})."
    if name == "gemini":
        _, model = await gemini_text_json("You are a connection test.", prompt,
                                          {"type": "object", "properties": {"ok": {"type": "boolean"}}}, timeout=60.0)
        return f"Gemini answered ({model})."
    if name in OPENAI_COMPATIBLE:
        _, model = await openai_compatible_chat(name, [{"role": "user", "content": prompt}], None, timeout=60.0)
        return f"{OPENAI_COMPATIBLE[name][0]} answered ({model})."
    raise VisionProviderError(f"Unknown AI provider '{name}'")
