"""App configuration. API keys live here, server-side only, never echoed to the frontend."""
import json
import os
import sys
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


def _resolve_data_dir() -> Path:
    """Always a per-user, writable app-data directory — correct both in dev
    and when frozen/installed under a read-only Program Files tree."""
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    elif sys.platform == "darwin":
        base = str(Path.home() / "Library" / "Application Support")
    else:
        base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / "RedThread"


DATA_DIR = _resolve_data_dir()
DATA_DIR.mkdir(parents=True, exist_ok=True)
UPLOAD_DIR = DATA_DIR / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

# User-editable settings (provider choice, and API keys while encryption is
# off) persist here across restarts. With encryption on, API keys live only
# in the encrypted vault (see app.core.vault) and are never written here.
SETTINGS_FILE = DATA_DIR / "app_settings.json"
SECRET_FIELDS = ("anthropic_api_key", "gemini_api_key", "openai_api_key", "xai_api_key", "custom_api_key")
PERSISTED_FIELDS = (
    "ai_provider",
    "anthropic_api_key",
    "claude_vision_model",
    "gemini_api_key",
    "gemini_vision_model",
    "openai_api_key",
    "openai_vision_model",
    "xai_api_key",
    "xai_model",
    "custom_api_key",
    "custom_base_url",
    "custom_model",
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="REDTHREAD_", env_file=".env", extra="ignore")

    ollama_host: str = "http://localhost:11434"
    ollama_vision_model: str = "qwen3-vl:2b"

    ai_provider: str = "claude"  # claude | ollama | gemini | openai | grok | custom
    anthropic_api_key: str = ""
    claude_vision_model: str = "claude-opus-5-5"
    gemini_api_key: str = ""
    gemini_vision_model: str = "gemini-2.5-flash"
    openai_api_key: str = ""
    openai_vision_model: str = "gpt-4o-mini"
    xai_api_key: str = ""
    xai_model: str = "grok-4"
    # Any service that speaks the OpenAI chat-completions API: OpenRouter,
    # DeepSeek, Mistral, Groq, Together, or a local LM Studio / vLLM server.
    custom_api_key: str = ""
    custom_base_url: str = ""
    custom_model: str = ""

    vision_call_delay_seconds: float = 3.0
    pdf_max_pages: int = 40  # pages past this are flagged for manual entry
    pdf_render_dpi: int = 200  # enough for typewritten text without oversized images
    dedup_fuzzy_threshold: int = 90
    watchlist_fuzzy_threshold: int = 85

    def persist(self) -> None:
        encrypted = (DATA_DIR / "vault.json").exists()
        data = {
            field: getattr(self, field) for field in PERSISTED_FIELDS
            if not (encrypted and field in SECRET_FIELDS)
        }
        SETTINGS_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _load_settings() -> Settings:
    instance = Settings()
    if SETTINGS_FILE.exists():
        try:
            saved = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            saved = {}
        for field in PERSISTED_FIELDS:
            value = saved.get(field)
            # A blank saved model name must not override the built-in
            # default: it made every Claude call fail and silently fall
            # back to the local engine.
            if field.endswith("_model") and not value:
                continue
            if field in saved:
                setattr(instance, field, value)
    return instance


settings = _load_settings()
