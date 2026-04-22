"""
bot/handlers.py — Telegram command handlers.

Commands:
  /search   — search with optional industry filter
  /industry — browse/set industry filter interactively
  /repeat   — re-run last search
  /history  — recent searches
  /status   — usage stats
  /export   — download CSV
  /clear    — delete saved data
  /help     — usage guide
"""

from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from formatters import (
    HELP_TEXT,
    SEARCHING_TEXT,
    format_industry_list,
    format_search_results,
    md2,
)
from config import settings
from models import SearchRequest
from search_service import execute_search, execute_person_search
from industries import INDUSTRY_LIST, is_valid_industry
from logger import log
from rate_limiter import rate_limiter
from session import sessions
from storage import clear_results, get_export_path


# ── /start ────────────────────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    log.info("/start from {uid}", uid=user.id)
    await update.message.reply_text(
        f"👋 Hello, {md2(user.first_name)}\\!\n\n" + HELP_TEXT,
        parse_mode=ParseMode.MARKDOWN_V2,
    )


# ── /help ─────────────────────────────────────────────────────────────────────

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(HELP_TEXT, parse_mode=ParseMode.MARKDOWN_V2)


# ── /industries ───────────────────────────────────────────────────────────────

async def cmd_industries(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show all available industries as a tappable inline keyboard."""

    # Build rows of 2 buttons each
    buttons = []
    row = []
    for i, industry in enumerate(INDUSTRY_LIST):
        row.append(
            InlineKeyboardButton(
                text=industry,
                callback_data=f"industry_select:{industry}",
            )
        )
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)

    # Add a "No filter" button at the bottom
    buttons.append([
        InlineKeyboardButton("❌ No industry filter", callback_data="industry_select:none")
    ])

    reply_markup = InlineKeyboardMarkup(buttons)

    await update.message.reply_text(
        "🏭 *Select an industry filter*\n\n"
        "Tap an industry to set it, then run `/search`\\.\n"
        "Your selection is saved until you change it\\.",
        parse_mode=ParseMode.MARKDOWN_V2,
        reply_markup=reply_markup,
    )


async def callback_industry_select(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle inline keyboard industry selection."""
    query = update.callback_query
    await query.answer()

    data = query.data  # e.g. "industry_select:Healthcare"
    industry = data.split(":", 1)[1]

    user_id = query.from_user.id

    if industry == "none":
        context.user_data["industry"] = None
        await query.edit_message_text(
            "✅ Industry filter *removed*\\.\n\nYour next `/search` will cover all industries\\.",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
    else:
        context.user_data["industry"] = industry
        await query.edit_message_text(
            f"✅ Industry filter set to *{md2(industry)}*\\.\n\n"
            f"Now run your search:\n"
            f"`/search bookkeeper \\| Birmingham, Alabama`",
            parse_mode=ParseMode.MARKDOWN_V2,
        )

    log.info("User {uid} set industry filter: {i}", uid=user_id, i=industry)


# ── /search ───────────────────────────────────────────────────────────────────

async def cmd_search(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    raw_args = " ".join(context.args).strip() if context.args else ""

    if not raw_args or "|" not in raw_args:
      await update.message.reply_text(
            "⚠️ *Usage:*\n"
            "`/search job title \\| location`\n"
            "`/search job title \\| location \\| industry`\n"
            "`/search @Full Name \\| job title \\| location` \\(person lookup\\)\n\n"
            "_Examples:_\n"
            "`/search bookkeeper \\| Birmingham, Alabama`\n"
            "`/search @Shannon Lee \\| dental hygienist \\| Auburn, Alabama`",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return

    parts = [p.strip() for p in raw_args.split("|")]

 # Detect person search: first part starts with @
    if parts[0].startswith("@"):
        name = parts[0][1:].strip()
        job_title = parts[1] if len(parts) > 1 else ""
        location  = parts[2] if len(parts) > 2 else ""

        if not name or not job_title or not location:
            await update.message.reply_text(
                "⚠️ *Person search usage:*\n"
                "`/search @Full Name \\| job title \\| location`\n\n"
                "_Example:_\n"
                "`/search @Shannon Lee \\| dental hygienist \\| Auburn, Alabama`",
                parse_mode=ParseMode.MARKDOWN_V2,
            )
            return

        await _run_person_search(update, context, name, job_title, location)
        return
    # Regular search
    job_title = parts[0] if len(parts) > 0 else ""
    location  = parts[1] if len(parts) > 1 else ""
    inline_industry = parts[2] if len(parts) > 2 else None
    saved_industry  = context.user_data.get("industry")
    industry = inline_industry or saved_industry or None

    if inline_industry and not is_valid_industry(inline_industry):
        close = [i for i in INDUSTRY_LIST if inline_industry.lower() in i.lower()]
        suggestion = f"\n\nDid you mean: *{md2(close[0])}*?" if close else \
                     f"\n\nUse /industries to see all options\\."
        await update.message.reply_text(
            f"⚠️ Unknown industry: *{md2(inline_industry)}*{suggestion}",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return

    if not job_title or not location:
        await update.message.reply_text(
            "⚠️ Both *job title* and *location* are required\\.",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return

    await _run_search(update, context, job_title, location, industry)

# ── /repeat ───────────────────────────────────────────────────────────────────

async def cmd_repeat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    last = sessions.get_last_search(user.id)
    if not last:
        await update.message.reply_text(
            "ℹ️ No previous search found\\. Run `/search` first\\.",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return
    job_title, location = last
    industry = context.user_data.get("industry")
    ind_text = f" \\[{md2(industry)}\\]" if industry else ""
    await update.message.reply_text(
        f"🔄 Repeating: *{md2(job_title)}* in *{md2(location)}*{ind_text}",
        parse_mode=ParseMode.MARKDOWN_V2,
    )
    await _run_search(update, context, job_title, location, industry)


# ── /history ──────────────────────────────────────────────────────────────────

async def cmd_history(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    history = sessions.get_history(user.id)
    if not history:
        await update.message.reply_text(
            "📭 No search history yet\\.",
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
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN_V2)


# ── /status ───────────────────────────────────────────────────────────────────

async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    rl = rate_limiter.stats(user.id)
    sess = sessions.get_stats(user.id)
    industry = context.user_data.get("industry")
    ind_line = f"🏭 Active filter: *{md2(industry)}*\n" if industry else "🏭 Industry filter: _none_\n"

    last_search = (
        f"*{md2(sess['last_job_title'])}* in *{md2(sess['last_location'])}*"
        if sess["last_job_title"] else "_None yet_"
    )
    msg = (
        f"📊 *Your Usage Stats*\n\n"
        f"🔍 Searches this hour: `{rl['searches_in_window']}/{rl['max_per_window']}`\n"
        f"✅ Remaining: `{rl['remaining']}`\n"
        f"📈 Total searches: `{sess['total_searches']}`\n"
        f"🕐 Last search: {last_search}\n"
        f"{ind_line}\n"
        f"💡 Use /industries to change your industry filter\\."
    )
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN_V2)


# ── /export ───────────────────────────────────────────────────────────────────

async def cmd_export(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    csv_path = get_export_path(user.id)
    if csv_path is None:
        await update.message.reply_text(
            "📭 No results saved yet\\. Run a `/search` first\\.",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return
    try:
        with open(csv_path, "rb") as f:
            await update.message.reply_document(
                document=f,
                filename=f"linkedin_results_{user.id}.csv",
                caption="📊 Your saved LinkedIn search results\\.",
                parse_mode=ParseMode.MARKDOWN_V2,
            )
    except Exception as exc:
        await update.message.reply_text(
            f"❌ Export failed: {md2(str(exc))}",
            parse_mode=ParseMode.MARKDOWN_V2,
        )


# ── /clear ────────────────────────────────────────────────────────────────────

async def cmd_clear(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    await clear_results(user.id)
    await update.message.reply_text(
        "🗑️ Your saved results have been deleted\\.",
        parse_mode=ParseMode.MARKDOWN_V2,
    )


# ── Shared search runner ──────────────────────────────────────────────────────

async def _run_search(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    job_title: str,
    location: str,
    industry: str | None,
) -> None:
    user = update.effective_user
    log.info(
        "Search — job:'{j}' loc:'{l}' industry:'{i}' user:{u}",
        j=job_title, l=location, i=industry or "any", u=user.id,
    )

    try:
        request = SearchRequest(
            job_title=job_title,
            location=location,
            industry=industry,
            user_id=user.id,
            chat_id=update.effective_chat.id,
        )
    except Exception as exc:
        await update.message.reply_text(
            f"⚠️ Invalid input: {md2(str(exc))}",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return

    status_msg = await update.message.reply_text(
        SEARCHING_TEXT, parse_mode=ParseMode.MARKDOWN_V2
    )

    search_result = await execute_search(request)

    try:
        await status_msg.delete()
    except Exception:
        pass

    if search_result.error == "already_searching":
        await update.message.reply_text(
            "⏳ A search is already running\\. Please wait\\.",
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

    messages = format_search_results(search_result)
    for msg in messages:
        await update.message.reply_text(
            msg,
            parse_mode=ParseMode.MARKDOWN_V2,
            disable_web_page_preview=True,
        )


# ── Fallback ──────────────────────────────────────────────────────────────────

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = update.message.text or ""
    if "|" in text:
        await update.message.reply_text(
            f"💡 Did you mean: `/search {md2(text)}`?",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
    else:
        await update.message.reply_text(
            "ℹ️ Use /help to see available commands\\.",
            parse_mode=ParseMode.MARKDOWN_V2,
        )


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    log.exception("Unhandled exception: {e}", e=context.error)
    if isinstance(update, Update) and update.effective_message:
        await update.effective_message.reply_text(
            "❌ An unexpected error occurred\\. Please try again\\.",
            parse_mode=ParseMode.MARKDOWN_V2,
        )

async def _run_person_search(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    name: str,
    job_title: str,
    location: str,
) -> None:
    user = update.effective_user
    log.info("Person search — name:'{n}' job:'{j}' user:{u}", n=name, j=job_title, u=user.id)

    try:
        request = SearchRequest(
            name=name,
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

    status_msg = await update.message.reply_text(
        f"🔍 Searching for *{md2(name)}* \\— *{md2(job_title)}*\\.\\.\\.",
        parse_mode=ParseMode.MARKDOWN_V2,
    )

    search_result = await execute_person_search(request)

    try:
        await status_msg.delete()
    except Exception:
        pass

    if search_result.error == "already_searching":
        await update.message.reply_text("⏳ A search is already running\\. Please wait\\.", parse_mode=ParseMode.MARKDOWN_V2)
        return

    if search_result.error and search_result.error.startswith("rate_limited:"):
        reason = search_result.error.split(":", 1)[1]
        await update.message.reply_text(f"🚦 *Rate limit reached*\n\n{md2(reason)}", parse_mode=ParseMode.MARKDOWN_V2)
        return

    messages = format_search_results(search_result)
    for msg in messages:
        await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN_V2, disable_web_page_preview=True)
