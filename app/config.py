"""Application configuration for public market-data access."""

from dataclasses import dataclass
import os

try:
    from dotenv import load_dotenv
except ModuleNotFoundError:
    def load_dotenv() -> bool:
        """Fallback when python-dotenv has not been installed yet."""
        return False

load_dotenv()

DEBUG = os.getenv("DEBUG", "false").strip().lower() == "true"


@dataclass(frozen=True)
class Settings:
    """Runtime settings loaded from environment variables."""

    binance_base_url: str = os.getenv("BINANCE_BASE_URL", "https://api.binance.com")
    binance_base_url_order: str = (
        os.getenv("BINANCE_BASE_URL_ORDER", "data-api,api").strip()
        or "data-api,api"
    )
    default_quote_asset: str = os.getenv("DEFAULT_QUOTE_ASSET", "USDT")
    log_level: str = os.getenv("LOG_LEVEL", "INFO")
    supabase_database_url: str = os.getenv("SUPABASE_DATABASE_URL", "").strip()
    persistence_backend: str = os.getenv("PERSISTENCE_BACKEND", "json").strip() or "json"
    telegram_bot_token: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    telegram_chat_id: str = os.getenv("TELEGRAM_CHAT_ID", "")
    telegram_alerts_enabled: bool = (
        os.getenv("TELEGRAM_ALERTS_ENABLED", "false").lower() == "true"
    )


settings = Settings()

BINANCE_BASE_URL_ORDER = settings.binance_base_url_order
BINANCE_BASE_URL_ORDER_IS_SET = (
    os.getenv("BINANCE_BASE_URL_ORDER") is not None
    and os.getenv("BINANCE_BASE_URL_ORDER", "").strip() != ""
)
SUPABASE_DATABASE_URL = settings.supabase_database_url
PERSISTENCE_BACKEND = settings.persistence_backend
USE_SUPABASE = (
    PERSISTENCE_BACKEND.lower() == "supabase"
    and SUPABASE_DATABASE_URL != ""
)
