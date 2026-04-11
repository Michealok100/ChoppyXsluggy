"""
bot/formatters.py — Telegram message formatting helpers.

Keeps all MarkdownV2 escaping and layout logic out of the handler files.
"""

from __future__ import annotations

from models import Person, SearchResult
from synonyms import get_synonyms

# Characters that must be escaped in MarkdownV2
_MD2_ESCAPE = r"_*[]()~`>#+-=|{}.!"


def md2(text: str) -> str:
    """Escape *text* for Telegram MarkdownV2."""
    for ch in _MD2_ESCAPE:
        text = text.replace(ch, f"\\{ch}")
    return text


# ── Individual blocks ────────────────────────────────────────────────────────


def format_person(person: Person, index: int) -> str:
    """Return one person as a MarkdownV2-safe Telegram block."""
    name = md2(person.name)
    title = md2(person.title)
    company = md2(person.company)
    url = person.linkedin_url  # URLs must NOT be escaped

    return (
        f"*{index}\\.* 👤 *{name}*\n"
        f"   💼 {title}\n"
        f"   🏢 {company}\n"
        f"   🔗 [LinkedIn Profile]({url})\n"
    )


# ── Full result messages ─────────────────────────────────────────────────────


def format_search_results(result: SearchResult) -> list[str]:
    """
    Convert a SearchResult into a list of Telegram messages.

    Multiple messages are returned when the result list is large
    (Telegram has a 4096-char message limit).
    """
    if not result.found:
        return [_format_no_results(result)]

    messages: list[str] = []
    job = md2(result.request.job_title)
    loc = md2(result.request.location)
    count = len(result.people)

    # ── Header ───────────────────────────────────────────────────────────────
    fallback_note = ""
    if result.fallback_level == 1:
        fallback_note = "\n_\\(broadened title search\\)_"
    elif result.fallback_level == 2:
        fallback_note = "\n_\\(broadened location search\\)_"
    elif result.fallback_level == 3:
        fallback_note = "\n_\\(location removed — national results\\)_"

    header = (
        f"🔍 *Search Results*\n"
        f"📌 *Role:* {job}\n"
        f"📍 *Location:* {loc}\n"
        f"👥 *Found:* {count} professionals{fallback_note}\n"
        f"{'─' * 30}\n"
    )

    current_msg = header
    batch_start = 1

    for i, person in enumerate(result.people, start=1):
        block = format_person(person, i)

        # Telegram limit is 4096 chars; leave headroom for safety
        if len(current_msg) + len(block) > 3800:
            messages.append(current_msg)
            current_msg = f"_\\(continued — {batch_start}\\-{i-1} above\\)_\n\n"
            batch_start = i

        current_msg += block + "\n"

    if current_msg.strip():
        messages.append(current_msg)

    # ── Footer on last message ───────────────────────────────────────────────
    footer = (
        "\n📥 Use /export to download results as CSV\\.\n"
        "🔎 Run /search again for a new query\\."
    )
    messages[-1] += footer

    return messages


def _format_no_results(result: SearchResult) -> str:
    job = md2(result.request.job_title)
    loc = md2(result.request.location)
    synonyms = get_synonyms(result.request.job_title)
    syn_text = (
        "\n\n💡 *Suggested alternatives:*\n" +
        "\n".join(f"  • {md2(s)}" for s in synonyms[:5])
        if synonyms
        else ""
    )
    return (
        f"😕 *No results found*\n\n"
        f"I searched for *{job}* in *{loc}* using multiple fallback "
        f"strategies but couldn't find matching LinkedIn profiles\\."
        f"{syn_text}\n\n"
        f"Try:\n"
        f"  • A different job title or synonym\n"
        f"  • A broader location \\(state instead of city\\)\n"
        f"  • `/search {job} \\| {md2(result.request.location.split(',')[1].strip() if ',' in result.request.location else result.request.location)}`"
    )


# ── Static help text ─────────────────────────────────────────────────────────


HELP_TEXT = """
🤖 *LinkedIn X\\-Ray Search Bot*
_Find professionals by role \\& location_

━━━━━━━━━━━━━━━━━━━━━
*Commands*
━━━━━━━━━━━━━━━━━━━━━

🔍 */search* `job title | location`
Search for professionals on LinkedIn\\.
_Example:_ `/search bookkeeper | Birmingham, Alabama`
_Example:_ `/search software engineer | Austin, TX`

📥 */export*
Download all your previous results as a CSV file\\.

❓ */help*
Show this message\\.

━━━━━━━━━━━━━━━━━━━━━
*How it works*
━━━━━━━━━━━━━━━━━━━━━
The bot uses Google X\\-ray search against LinkedIn to find
people currently working in your target role\\. Results include:
👤 Full name  💼 Job title  🏢 Company  🔗 LinkedIn URL

If no results are found, the bot automatically broadens the
search \\(synonyms → larger area → national\\)\\.

━━━━━━━━━━━━━━━━━━━━━
*Tips*
━━━━━━━━━━━━━━━━━━━━━
• Use common job title variations for best results
• State\\-level searches return more people than city\\-level
• Run multiple searches — results are saved cumulatively
""".strip()


SEARCHING_TEXT = "🔍 Searching LinkedIn… This may take 10\\-20 seconds\\."
