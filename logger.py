"""
utils/logger.py — Centralised logging via loguru.

Usage:
    from utils.logger import log
    log.info("message")
    log.error("something failed: {err}", err=e)
"""

import sys
from pathlib import Path

from loguru import logger as log

from config import settings

# Remove loguru's default handler so we control formatting fully
log.remove()

# ── Console handler ──────────────────────────────────────────────────────────
log.add(
    sys.stderr,
    level=settings.LOG_LEVEL,
    format=(
        "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{line}</cyan> — "
        "<level>{message}</level>"
    ),
    colorize=True,
)

# ── Rotating file handler ────────────────────────────────────────────────────
_log_dir = Path("logs")
_log_dir.mkdir(exist_ok=True)

log.add(
    _log_dir / "bot_{time:YYYY-MM-DD}.log",
    level="DEBUG",
    rotation="00:00",       # new file every midnight
    retention="14 days",
    compression="zip",
    format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{line} — {message}",
    enqueue=True,           # async-safe
)

__all__ = ["log"]
