"""Application configuration for public market-data access."""

from dataclasses import dataclass
import os


@dataclass(frozen=True)
class Settings:
    """Runtime settings loaded from environment variables."""

    binance_base_url: str = os.getenv("BINANCE_BASE_URL", "https://api.binance.com")
    default_quote_asset: str = os.getenv("DEFAULT_QUOTE_ASSET", "USDT")
    log_level: str = os.getenv("LOG_LEVEL", "INFO")


settings = Settings()
