"""
config.py — Central configuration loaded from environment / .env

Import `settings` everywhere; never read os.environ directly.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# Load .env from the project root (one level up from this file's parent)
_env_path = Path(__file__).parent / ".env"
load_dotenv(_env_path)


class Settings:
    # ── Required ────────────────────────────────
    TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    SERPAPI_KEY: str = os.getenv("SERPAPI_KEY", "")

    # ── Search tuning ───────────────────────────
    MAX_RESULTS: int = int(os.getenv("MAX_RESULTS", "15"))
    SEARCH_PAGES: int = int(os.getenv("SEARCH_PAGES", "2"))
    REQUEST_DELAY: float = float(os.getenv("REQUEST_DELAY", "1.0"))

    # ── Storage ─────────────────────────────────
    DATA_DIR: Path = Path(os.getenv("DATA_DIR", "data"))

    # ── Logging ─────────────────────────────────
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

    # ── SerpAPI endpoint ────────────────────────
    SERPAPI_URL: str = "https://serpapi.com/search"

    def validate(self) -> None:
        """Raise early if required credentials are missing."""
        if not self.TELEGRAM_BOT_TOKEN:
            raise EnvironmentError("TELEGRAM_BOT_TOKEN is not set in .env")
        if not self.SERPAPI_KEY:
            raise EnvironmentError("SERPAPI_KEY is not set in .env")
        self.DATA_DIR.mkdir(parents=True, exist_ok=True)


settings = Settings()
