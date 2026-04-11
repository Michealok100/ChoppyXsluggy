"""
main.py — Application entrypoint.
Run with:  python main.py
           python main.py --mock     (use mock SerpAPI client, no real API calls)
"""
from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from telegram import BotCommand
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
)
from handlers import (
    cmd_clear,
    cmd_export,
    cmd_help,
    cmd_history,
    cmd_repeat,
    cmd_search,
    cmd_start,
    cmd_status,
    error_handler,
    handle_text,
)
from config import settings
from logger import log

async def post_init(application: Application) -> None:
    """Register the bot's command menu visible in Telegram clients."""
    await application.bot.set_my_commands(
        [
            BotCommand("search",  "Search professionals by role & location"),
            BotCommand("repeat",  "Re-run your last search"),
            BotCommand("history", "Show your recent searches"),
            BotCommand("status",  "Check your usage & rate limits"),
            BotCommand("export",  "Download results as CSV"),
            BotCommand("clear",   "Delete your saved results"),
            BotCommand("help",    "Show usage instructions"),
        ]
    )
    log.info("Bot command menu registered.")

def build_application() -> Application:
    app = (
        Application.builder()
        .token(settings.TELEGRAM_BOT_TOKEN)
        .post_init(post_init)
        .build()
    )
    app.add_handler(CommandHandler("start",   cmd_start))
    app.add_handler(CommandHandler("help",    cmd_help))
    app.add_handler(CommandHandler("search",  cmd_search))
    app.add_handler(CommandHandler("repeat",  cmd_repeat))
    app.add_handler(CommandHandler("history", cmd_history))
    app.add_handler(CommandHandler("status",  cmd_status))
    app.add_handler(CommandHandler("export",  cmd_export))
    app.add_handler(CommandHandler("clear",   cmd_clear))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_error_handler(error_handler)
    return app

def main() -> None:
    # --mock flag: override SERPAPI_KEY so the mock client is used
    if "--mock" in sys.argv:
        import os
        os.environ["SERPAPI_KEY"] = "MOCK"
        log.warning("Running in MOCK mode — no real API calls will be made.")
    settings.validate()
    log.info("Starting LinkedIn X-ray Bot…")
    app = build_application()
    log.info("Bot is running. Press Ctrl+C to stop.")
    app.run_polling(
        allowed_updates=["message"],
        drop_pending_updates=True,
    )

if __name__ == "__main__":
    main()
