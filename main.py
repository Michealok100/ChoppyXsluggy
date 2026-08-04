"""
main.py — Application entrypoint with webhook support for Render.
Run with:  python main.py
           python main.py --mock     (use mock SerpAPI client, no real API calls)
"""
from __future__ import annotations
import sys
import os
import asyncio
import threading
from pathlib import Path
from flask import Flask, request

sys.path.insert(0, str(Path(__file__).parent))

from telegram import BotCommand, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
)
from handlers import (
    cmd_clear,
    cmd_company,
    cmd_export,
    cmd_help,
    cmd_history,
    cmd_industries,
    cmd_repeat,
    cmd_search,
    cmd_start,
    cmd_status,
    callback_industry_select,
    error_handler,
    handle_text,
)
from config import settings
from logger import log

# Flask app for webhook
flask_app = Flask(__name__)

# Global telegram app
tg_app = None
loop = None


async def post_init(application: Application) -> None:
    """Register the bot's command menu visible in Telegram clients."""
    await application.bot.set_my_commands(
        [
            BotCommand("search",     "Search professionals by role & location"),
            BotCommand("company",    "Find employees at a company"),
            BotCommand("industries", "Browse and select industry filter"),
            BotCommand("repeat",     "Re-run your last search"),
            BotCommand("history",    "Show your recent searches"),
            BotCommand("status",     "Check your usage & rate limits"),
            BotCommand("export",     "Download results as CSV"),
            BotCommand("clear",      "Delete your saved results"),
            BotCommand("help",       "Show usage instructions"),
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
    app.add_handler(CommandHandler("start",      cmd_start))
    app.add_handler(CommandHandler("help",       cmd_help))
    app.add_handler(CommandHandler("search",     cmd_search))
    app.add_handler(CommandHandler("company",    cmd_company))
    app.add_handler(CommandHandler("industries", cmd_industries))
    app.add_handler(CommandHandler("repeat",     cmd_repeat))
    app.add_handler(CommandHandler("history",    cmd_history))
    app.add_handler(CommandHandler("status",     cmd_status))
    app.add_handler(CommandHandler("export",     cmd_export))
    app.add_handler(CommandHandler("clear",      cmd_clear))
    
    # Callback handler for industry selection
    app.add_handler(CallbackQueryHandler(callback_industry_select, pattern="^industry_select:"))
    
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_error_handler(error_handler)
    return app


@flask_app.route('/webhook', methods=['POST'])
def webhook_handler():
    """Handle incoming Telegram updates via webhook"""
    try:
        data = request.get_json()
        if data and tg_app:
            update = Update.de_json(data, tg_app.bot)
            # Run the async function in the event loop
            asyncio.run_coroutine_threadsafe(
                tg_app.process_update(update), 
                loop
            )
        return 'ok', 200
    except Exception as e:
        log.error(f"Webhook error: {e}")
        return 'error', 500


@flask_app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint for Render"""
    return 'Bot is running', 200


def run_bot():
    """Run the Telegram bot in a separate thread"""
    global tg_app, loop
    
    try:
        settings.validate()
        log.info("Starting LinkedIn X-ray Bot…")
        
        tg_app = build_application()
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        # Start the bot
        log.info("Bot started successfully.")
        loop.run_until_complete(tg_app.initialize())
        loop.run_until_complete(tg_app.post_init(tg_app))
        
        # Keep bot running
        while True:
            loop.run_until_complete(asyncio.sleep(0.1))
            
    except KeyboardInterrupt:
        log.info("Shutting down bot...")
    except Exception as e:
        log.error(f"Bot error: {e}")


def main() -> None:
    # --mock flag: override SERPAPI_KEY so the mock client is used
    if "--mock" in sys.argv:
        os.environ["SERPAPI_KEY"] = "MOCK"
        log.warning("Running in MOCK mode — no real API calls will be made.")
    
    webhook_url = os.getenv('WEBHOOK_URL')
    port = int(os.getenv('PORT', 10000))
    
    log.info(f"Starting Flask server on port {port}...")
    if webhook_url:
        log.info(f"Webhook mode enabled: {webhook_url}")
    
    # Start bot in background thread
    bot_thread = threading.Thread(target=run_bot, daemon=True)
    bot_thread.start()
    
    # Give bot time to initialize
    import time
    time.sleep(2)
    
    # Start Flask server on main thread
    flask_app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()
