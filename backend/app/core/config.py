"""
Application settings — single source of truth for environment config.

Settings are declared via pydantic-settings, which gives:
    - Type validation at instantiation (missing required vars fail fast)
    - IDE autocomplete and type-checking on every access
    - One declarative surface for all env-dependent configuration

load_dotenv() is called on import to populate os.environ from .env.
This is needed because third-party libraries (ChatOpenAI, yfinance, etc.)
read from os.environ directly and don't know about our Settings class.
With this single import-time side effect, the rest of the app needs no
further env-loading code.
"""

import warnings
from functools import lru_cache

from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict

# Populate os.environ from .env before any Settings instantiation
# or third-party library imports that depend on env vars.
load_dotenv()


class Settings(BaseSettings):
    """Typed application settings.

    Field rules:
        - No default value → required. Missing => ValidationError at boot.
        - With default value → optional. Override via env var or .env.

    Versioning:
        V1: OpenAI credentials only.
        V2: + DATABASE_URL (Postgres).
        V3: + TAVILY_API_KEY, + OPENAI_MODEL_SYNTHESIZER upgraded to gpt-4o.
        V7: + TELEGRAM_BOT_TOKEN (Telegram delivery channel).
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,  # OPENAI_API_KEY and openai_api_key both match
        extra="ignore",  # don't error on unknown env vars
    )

    # ─── Required ───
    openai_api_key: str
    database_url: str
    tavily_api_key: str

    # ─── Optional with defaults ───
    openai_model_synthesizer: str = "gpt-4o-mini"
    telegram_bot_token: str | None = None


@lru_cache
def get_settings() -> Settings:
    """Return the singleton Settings instance.

    @lru_cache means .env is parsed and validated once on first call;
    every subsequent call returns the cached instance for free. This is
    the standard FastAPI pattern for settings shared across handlers.

    Use in FastAPI routes via:
        @app.get(...)
        def handler(settings: Settings = Depends(get_settings)):
            ...
    """
    return Settings()


warnings.filterwarnings(
    "ignore",
    message="Pydantic serializer warnings",
    category=UserWarning,
)
