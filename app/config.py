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


@dataclass(frozen=True)
class Settings:
    """Runtime settings loaded from environment variables."""

    binance_base_url: str = os.getenv("BINANCE_BASE_URL", "https://api.binance.com")
    default_quote_asset: str = os.getenv("DEFAULT_QUOTE_ASSET", "USDT")
    log_level: str = os.getenv("LOG_LEVEL", "INFO")
    telegram_bot_token: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    telegram_chat_id: str = os.getenv("TELEGRAM_CHAT_ID", "")
    telegram_alerts_enabled: bool = (
        os.getenv("TELEGRAM_ALERTS_ENABLED", "false").lower() == "true"
    )


settings = Settings()
