from fastapi import APIRouter, HTTPException
from app.core import vault
from app.core.config import settings
from app.schemas import schemas
from app.services.ollama_client import PROVIDERS, VisionProviderError, test_provider

router = APIRouter(prefix="/api/settings", tags=["settings"])

SECRET_INPUTS = ("anthropic_api_key", "gemini_api_key", "openai_api_key", "xai_api_key", "custom_api_key")
PLAIN_INPUTS = ("claude_vision_model", "gemini_vision_model", "openai_vision_model", "xai_model",
                "custom_base_url", "custom_model")


def _to_out() -> schemas.AppSettingsOut:
    return schemas.AppSettingsOut(
        ai_provider=settings.ai_provider,
        ollama_vision_model=settings.ollama_vision_model,
        claude_vision_model=settings.claude_vision_model,
        gemini_vision_model=settings.gemini_vision_model,
        openai_vision_model=settings.openai_vision_model,
        xai_model=settings.xai_model,
        custom_base_url=settings.custom_base_url,
        custom_model=settings.custom_model,
        encryption_enabled=vault.is_enabled(),
        anthropic_key_configured=bool(settings.anthropic_api_key),
        gemini_key_configured=bool(settings.gemini_api_key),
        openai_key_configured=bool(settings.openai_api_key),
        xai_key_configured=bool(settings.xai_api_key),
        custom_key_configured=bool(settings.custom_api_key),
    )


@router.get("", response_model=schemas.AppSettingsOut)
def get_settings():
    return _to_out()


@router.put("", response_model=schemas.AppSettingsOut)
def update_settings(payload: schemas.AppSettingsUpdate):
    if payload.ai_provider is not None:
        if payload.ai_provider not in PROVIDERS:
            raise HTTPException(status_code=422, detail=f"Unknown AI provider '{payload.ai_provider}'")
        settings.ai_provider = payload.ai_provider
    if payload.custom_base_url and not payload.custom_base_url.strip().startswith(("http://", "https://")):
        raise HTTPException(status_code=422, detail="The address must start with https:// (or http:// for a local server)")
    for field in PLAIN_INPUTS:
        value = getattr(payload, field)
        if value is not None:
            setattr(settings, field, value.strip())
    new_secrets = {field: getattr(payload, field).strip() for field in SECRET_INPUTS if getattr(payload, field) is not None}
    for field, value in new_secrets.items():
        setattr(settings, field, value)
    if new_secrets and vault.is_enabled():
        vault.save_secrets(new_secrets)  # API keys live only in the encrypted vault

    settings.persist()  # never writes API keys while encryption is on
    return _to_out()


@router.post("/test", response_model=schemas.ProviderTestOut)
async def test_settings():
    """Send a tiny text request to the selected provider (no case data)."""
    try:
        detail = await test_provider(settings.ai_provider)
    except VisionProviderError as exc:
        return schemas.ProviderTestOut(ok=False, message=str(exc))
    return schemas.ProviderTestOut(ok=True, message=detail)
