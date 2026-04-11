"""
bot/handlers.py — Telegram command and message handlers.

Commands:
  /start   — welcome
  /help    — usage guide
  /search  — main X-ray search
  /repeat  — re-run last search
  /history — show recent searches
  /status  — rate limit + usage stats
  /export  — download CSV
  /clear   — delete saved CSV data
"""

from __future__ import annotations

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from bot.formatters import (
    HELP_TEXT,
    SEARCHING_TEXT,
    format_search_results,
    md2,
)
from config import settings
from models import SearchRequest
from scraper.search_service import execute_search
from utils.logger import log
from utils.rate_limiter import rate_limiter
from utils.session import sessions
from utils.storage import clear_results, get_export_path


# ── /start ────────────────────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    log.info("/start from user {uid} ({name})", uid=user.id, name=user.first_name)
    await update.message.reply_text(
        f"👋 Hello, {md2(user.first_name)}\\!\n\n" + HELP_TEXT,
        parse_mode=ParseMode.MARKDOWN_V2,
    )


# ── /help ─────────────────────────────────────────────────────────────────────

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(HELP_TEXT, parse_mode=ParseMode.MARKDOWN_V2)


# ── /search ───────────────────────────────────────────────────────────────────

async def cmd_search(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Main search command.
    Usage: /search job title | location
    """
    user = update.effective_user
    raw_args = " ".join(context.args).strip() if context.args else ""

    if "|" not in raw_args:
        await update.message.reply_text(
            "⚠️ *Usage:* `/search job title \\| location`\n\n"
            "_Example:_ `/search bookkeeper \\| Birmingham, Alabama`",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return

    parts = raw_args.split("|", maxsplit=1)
    job_title = parts[0].strip()
    location = parts[1].strip()

    if not job_title or not location:
        await update.message.reply_text(
            "⚠️ Both a *job title* and a *location* are required\\.",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return

    await _run_search(update, context, job_title, location)


# ── /repeat ───────────────────────────────────────────────────────────────────

async def cmd_repeat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Re-run the user's most recent search."""
    user = update.effective_user
    last = sessions.get_last_search(user.id)

    if not last:
        await update.message.reply_text(
            "ℹ️ No previous search found\\. Run `/search` first\\.",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return

    job_title, location = last
    await update.message.reply_text(
        f"🔄 Repeating: *{md2(job_title)}* in *{md2(location)}*",
        parse_mode=ParseMode.MARKDOWN_V2,
    )
    await _run_search(update, context, job_title, location)


# ── /history ──────────────────────────────────────────────────────────────────

async def cmd_history(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show the user's last 10 searches."""
    user = update.effective_user
    history = sessions.get_history(user.id)

    if not history:
        await update.message.reply_text(
            "📭 No search history yet\\. Run `/search` to get started\\.",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return

    lines = ["📋 *Your Recent Searches*\n"]
    for i, entry in enumerate(history, 1):
        ts = entry["ts"].strftime("%b %d %H:%M UTC")
        found_txt = f"{entry['found']} found" if entry["found"] else "no results"
        lines.append(
            f"{i}\\. *{md2(entry['job_title'])}* in {md2(entry['location'])}\n"
            f"   _{md2(ts)} · {found_txt}_\n"
        )

    await update.message.reply_text(
        "\n".join(lines),
        parse_mode=ParseMode.MARKDOWN_V2,
    )


# ── /status ───────────────────────────────────────────────────────────────────

async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show rate-limit usage and session stats."""
    user = update.effective_user
    rl = rate_limiter.stats(user.id)
    sess = sessions.get_stats(user.id)

    last_search = (
        f"*{md2(sess['last_job_title'])}* in *{md2(sess['last_location'])}*"
        if sess["last_job_title"]
        else "_None yet_"
    )

    msg = (
        f"📊 *Your Usage Stats*\n\n"
        f"🔍 Searches this hour: `{rl['searches_in_window']}/{rl['max_per_window']}`\n"
        f"✅ Remaining: `{rl['remaining']}`\n"
        f"📈 Total searches: `{sess['total_searches']}`\n"
        f"🕐 Last search: {last_search}\n\n"
        f"💡 Use `/repeat` to re\\-run your last search\\."
    )
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN_V2)


# ── /export ───────────────────────────────────────────────────────────────────

async def cmd_export(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send the user's accumulated CSV results as a file download."""
    user = update.effective_user
    log.info("/export from user {uid}", uid=user.id)

    csv_path = get_export_path(user.id)

    if csv_path is None:
        await update.message.reply_text(
            "📭 No results saved yet\\.\n\nRun a `/search` first, then use `/export`\\.",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return

    try:
        with open(csv_path, "rb") as f:
            await update.message.reply_document(
                document=f,
                filename=f"linkedin_results_{user.id}.csv",
                caption=(
                    f"📊 Your saved LinkedIn search results\\.\n"
                    f"File: `{md2(csv_path.name)}`"
                ),
                parse_mode=ParseMode.MARKDOWN_V2,
            )
        log.info("CSV sent to user {uid}: {path}", uid=user.id, path=csv_path)
    except Exception as exc:
        log.error("Export failed for user {uid}: {e}", uid=user.id, e=exc)
        await update.message.reply_text(
            f"❌ Export failed: {md2(str(exc))}",
            parse_mode=ParseMode.MARKDOWN_V2,
        )


# ── /clear ────────────────────────────────────────────────────────────────────

async def cmd_clear(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Delete the user's saved CSV data."""
    user = update.effective_user
    await clear_results(user.id)
    log.info("/clear from user {uid}", uid=user.id)
    await update.message.reply_text(
        "🗑️ Your saved results have been deleted\\.\n\n"
        "Run `/search` to start fresh\\.",
        parse_mode=ParseMode.MARKDOWN_V2,
    )


# ── Shared search runner ──────────────────────────────────────────────────────

async def _run_search(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    job_title: str,
    location: str,
) -> None:
    """Core search logic shared by /search and /repeat."""
    user = update.effective_user
    log.info(
        "Search request — job: '{j}' | location: '{l}' | user: {uid}",
        j=job_title, l=location, uid=user.id,
    )

    # Build and validate request object
    try:
        request = SearchRequest(
            job_title=job_title,
            location=location,
            user_id=user.id,
            chat_id=update.effective_chat.id,
        )
    except Exception as exc:
        await update.message.reply_text(
            f"⚠️ Invalid input: {md2(str(exc))}",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return

    # Send "Searching…" status indicator
    status_msg = await update.message.reply_text(
        SEARCHING_TEXT, parse_mode=ParseMode.MARKDOWN_V2
    )

    search_result = await execute_search(request)

    # Delete the status message (best-effort)
    try:
        await status_msg.delete()
    except Exception:
        pass

    # Handle special error states before general formatting
    if search_result.error == "already_searching":
        await update.message.reply_text(
            "⏳ A search is already in progress\\. Please wait for it to finish\\.",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return

    if search_result.error and search_result.error.startswith("rate_limited:"):
        reason = search_result.error.split(":", 1)[1]
        await update.message.reply_text(
            f"🚦 *Rate limit reached*\n\n{md2(reason)}",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return

    # General result formatting
    messages = format_search_results(search_result)
    for msg in messages:
        await update.message.reply_text(
            msg,
            parse_mode=ParseMode.MARKDOWN_V2,
            disable_web_page_preview=True,
        )


# ── Fallback: plain text messages ─────────────────────────────────────────────

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = update.message.text or ""
    if "|" in text:
        await update.message.reply_text(
            f"💡 Did you mean to search? Try:\n`/search {md2(text)}`",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
    else:
        await update.message.reply_text(
            "ℹ️ Use /help to see available commands\\.",
            parse_mode=ParseMode.MARKDOWN_V2,
        )


# ── Global error handler ──────────────────────────────────────────────────────

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    log.exception("Unhandled exception: {e}", e=context.error)
    if isinstance(update, Update) and update.effective_message:
        await update.effective_message.reply_text(
            "❌ An unexpected error occurred\\. Please try again in a moment\\.",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
