"""
main.py — Application entrypoint with webhook support for Render.
Run with:  python main.py
           python main.py --mock     (use mock SerpAPI client, no real API calls)
"""
from __future__ import annotations
import sys
import os
import asyncio
from pathlib import Path
from flask import Flask, request

sys.path.insert(0, str(Path(__file__).parent))

from telegram import BotCommand, Update
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

# Flask app for webhook
flask_app = Flask(__name__)

# Global telegram app
tg_app = None


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
    
    # Set webhook if in production
    webhook_url = os.getenv('WEBHOOK_URL')
    if webhook_url:
        await application.bot.set_webhook(webhook_url)
        log.info(f"Webhook set to: {webhook_url}")


async def post_stop(application: Application) -> None:
    """Clean up webhook when bot stops"""
    await application.bot.delete_webhook()
    log.info("Webhook removed.")


def build_application() -> Application:
    app = (
        Application.builder()
        .token(settings.TELEGRAM_BOT_TOKEN)
        .post_init(post_init)
        .post_stop(post_stop)
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


@flask_app.route('/webhook', methods=['POST'])
async def webhook_handler():
    """Handle incoming Telegram updates via webhook"""
    try:
        data = request.get_json()
        if data:
            update = Update.de_json(data, tg_app.bot)
            await tg_app.process_update(update)
        return 'ok', 200
    except Exception as e:
        log.error(f"Webhook error: {e}")
        return 'error', 500


@flask_app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint for Render"""
    return 'Bot is running', 200


async def start_bot():
    """Start the Telegram bot"""
    global tg_app
    
    settings.validate()
    log.info("Starting LinkedIn X-ray Bot…")
    
    tg_app = build_application()
    
    async with tg_app:
        await tg_app.start()
        log.info("Bot started successfully.")
        
        # Keep bot running
        try:
            while True:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            log.info("Shutting down bot...")
            await tg_app.stop()


def main() -> None:
    # --mock flag: override SERPAPI_KEY so the mock client is used
    if "--mock" in sys.argv:
        os.environ["SERPAPI_KEY"] = "MOCK"
        log.warning("Running in MOCK mode — no real API calls will be made.")
    
    webhook_url = os.getenv('WEBHOOK_URL')
    port = int(os.getenv('PORT', 10000))
    
    # Start bot in background task
    bot_task = asyncio.create_task(start_bot())
    
    # Start Flask server
    log.info(f"Starting Flask server on port {port}...")
    if webhook_url:
        log.info(f"Webhook mode enabled: {webhook_url}")
    else:
        log.warning("WEBHOOK_URL not set, webhook mode may not work properly")
    
    flask_app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()
