"""
bot/formatters.py — Telegram MarkdownV2 message formatting.
"""

from __future__ import annotations

from models import Person, SearchResult
from industries import INDUSTRY_LIST
from synonyms import get_synonyms

_MD2_ESCAPE = r"_*[]()~`>#+-=|{}.!"


def md2(text: str) -> str:
    """Escape text for Telegram MarkdownV2."""
    for ch in _MD2_ESCAPE:
        text = text.replace(ch, f"\\{ch}")
    return text


def format_person(person: Person, index: int) -> str:
    confidence_emoji = {
        "HIGH": "✅",
        "MEDIUM": "🔵",
        "LOW": "⚠️",
    }.get(getattr(person, 'confidence', 'MEDIUM'), "❓")
    
    return (
        f"*{index}\\.* 👤 *{md2(person.name)}* {confidence_emoji}\n"
        f"   💼 {md2(person.title)}\n"
        f"   🏢 {md2(person.company)}\n"
        f"   🔗 [LinkedIn Profile]({person.linkedin_url})\n"
    )


def format_search_results(result: SearchResult) -> list[str]:
    if not result.found:
        return [_format_no_results(result)]

    messages: list[str] = []
    job      = md2(result.request.job_title)
    loc      = md2(result.request.location)
    industry = result.request.industry
    count    = len(result.people)

    # Fallback note
    fallback_note = {
        1: "\n_\\(broadened title search\\)_",
        2: "\n_\\(broadened location search\\)_",
        3: "\n_\\(industry filter kept, location removed\\)_",
        4: "\n_\\(location and industry filter removed\\)_",
    }.get(result.fallback_level, "")

    # Industry badge
    industry_line = f"🏭 *Industry:* {md2(industry)}\n" if industry else ""

    header = (
        f"🔍 *Search Results*\n"
        f"📌 *Role:* {job}\n"
        f"📍 *Location:* {loc}\n"
        f"{industry_line}"
        f"👥 *Found:* {count} professionals{fallback_note}\n"
        f"{'─' * 30}\n"
    )

    current_msg = header

    for i, person in enumerate(result.people, start=1):
        block = format_person(person, i)
        if len(current_msg) + len(block) > 3800:
            messages.append(current_msg)
            current_msg = ""
        current_msg += block + "\n"

    if current_msg.strip():
        messages.append(current_msg)

    messages[-1] += (
        "\n📥 Use /export to download results as CSV\\.\n"
        "🏭 Use /industries to change industry filter\\."
    )
    return messages


def format_company_results(result: SearchResult) -> list[str]:
    """Format company search results with company info header."""
    if not result.found:
        return [_format_no_company_results(result)]

    messages: list[str] = []
    company_name = md2(result.request.job_title)
    count = len(result.people)

    # Fallback note
    fallback_note = {
        0: "",
        1: "\n_\\(searched for employees keyword\\)_",
        2: "\n_\\(searched for manager keyword\\)_",
        3: "\n_\\(searched for director/executive keywords\\)_",
    }.get(result.fallback_level, "")

    header = (
        f"🏢 *Company Search Results*\n"
        f"🎯 *Company:* {company_name}\n"
        f"👥 *Found:* {count} professionals{fallback_note}\n"
        f"{'─' * 30}\n"
    )

    current_msg = header

    for i, person in enumerate(result.people, start=1):
        block = format_person(person, i)
        if len(current_msg) + len(block) > 3800:
            messages.append(current_msg)
            current_msg = ""
        current_msg += block + "\n"

    if current_msg.strip():
        messages.append(current_msg)

    messages[-1] += (
        "\n📥 Use /export to download results as CSV\\.\n"
        "🔍 Use /search to find specific roles\\."
    )
    return messages


def _format_no_company_results(result: SearchResult) -> str:
    """Format no results message for company search."""
    company_name = md2(result.request.job_title)
    return (
        f"😕 *No results found*\n\n"
        f"Searched for employees at *{company_name}*\\.\n\n"
        f"💡 *Suggestions:*\n"
        f"  • Try a different company name\n"
        f"  • Use a LinkedIn company URL directly\n"
        f"  • Use /search to find specific roles instead"
    )


def _format_no_results(result: SearchResult) -> str:
    job      = md2(result.request.job_title)
    loc      = md2(result.request.location)
    industry = result.request.industry
    synonyms = get_synonyms(result.request.job_title)

    ind_note = (
        f"\n\n💡 Industry filter *{md2(industry)}* was applied\\. "
        f"Try removing it with /industries → _No filter_\\."
        if industry else ""
    )
    syn_text = (
        "\n\n💡 *Suggested title alternatives:*\n" +
        "\n".join(f"  • {md2(s)}" for s in synonyms[:5])
        if synonyms else ""
    )
    industry_tag = f" \\[{md2(industry)}\\]" if industry else ""
    return (
        f"😕 *No results found*\n\n"
        f"Searched for *{job}* in *{loc}*"
        f"{industry_tag}\\."
        f"{ind_note}{syn_text}\n\n"
        f"Try:\n"
        f"  • A different job title\n"
        f"  • A broader location \\(state instead of city\\)\n"
        f"  • Removing the industry filter with /industries"
    )

def format_industry_list() -> str:
    """Return a plain-text list of all industries (for /help reference)."""
    lines = ["🏭 *Available Industry Filters*\n"]
    for ind in INDUSTRY_LIST:
        lines.append(f"  • {md2(ind)}")
    lines.append("\n_Use /industries to select one interactively\\._")
    return "\n".join(lines)


HELP_TEXT = """
🤖 *LinkedIn X\\-Ray Search Bot*
_Find professionals by role, location, company \\& industry_

━━━━━━━━━━━━━━━━━━━━━
*Commands*
━━━━━━━━━━━━━━━━━━━━━

🔍 */search* `job title | location`
🔍 */search* `job title | location | industry`
_Search LinkedIn for professionals by role\\._

Examples:
`/search bookkeeper | Birmingham, Alabama`
`/search nurse | Texas | Healthcare`
`/search software engineer | Austin, TX | Technology`

🏢 */company* `Company Name`
🏢 */company* `https://linkedin.com/company/...`
_Search for employees at a specific company\\._

Examples:
`/company Google`
`/company https://www.linkedin.com/company/anthropic`

🏭 */industries*
Browse and select an industry filter interactively\\.
Your selection is saved for all future searches\\.

🔄 */repeat* — Re\\-run your last search
📋 */history* — Your last 10 searches
📊 */status* — Usage stats \\& active filter
📥 */export* — Download results as CSV
🗑️ */clear* — Delete your saved results
❓ */help* — Show this message

━━━━━━━━━━━━━━━━━━━━━
*Features*
━━━━━━━━━━━━━━━━━━━━━
✅ Confidence scoring \\(HIGH/MEDIUM/LOW\\)
🏭 Industry filtering on role searches
📥 CSV export for all results
🔄 Search history tracking
""".strip()

SEARCHING_TEXT = "🔍 Searching LinkedIn… This may take 10\\-20 seconds\\."
