"""
utils/storage.py — CSV persistence for search results.

Each user gets their own CSV file so /export returns only their results.
Thread-safe via asyncio-friendly aiofiles.
"""

from __future__ import annotations

import csv
from io import StringIO
from logger import log

import aiofiles

from config import settings
from models import Person
from logger import log

_HEADERS = ["name", "title", "company", "linkedin_url", "timestamp"]


def _user_csv_path(user_id: int) -> Path:
    return settings.DATA_DIR / f"results_{user_id}.csv"


async def append_results(user_id: int, people: list[Person]) -> None:
    """Append *people* to the user's CSV, creating the file if needed."""
    if not people:
        return

    path = _user_csv_path(user_id)
    file_exists = path.exists()

    # Build CSV rows in memory first
    buf = StringIO()
    writer = csv.DictWriter(buf, fieldnames=_HEADERS)
    if not file_exists:
        writer.writeheader()
    for person in people:
        writer.writerow(person.as_csv_row())

    # Write asynchronously
    async with aiofiles.open(path, mode="a", newline="", encoding="utf-8") as f:
        await f.write(buf.getvalue())

    log.debug("Appended {n} rows to {path}", n=len(people), path=path)


async def read_all_results(user_id: int) -> list[dict]:
    """Return all stored rows for a user as a list of dicts."""
    path = _user_csv_path(user_id)
    if not path.exists():
        return []

    async with aiofiles.open(path, mode="r", encoding="utf-8") as f:
        content = await f.read()

    reader = csv.DictReader(StringIO(content))
    return list(reader)


async def clear_results(user_id: int) -> None:
    """Delete a user's CSV (used in tests / admin reset)."""
    path = _user_csv_path(user_id)
    if path.exists():
        path.unlink()
        log.info("Cleared results for user {uid}", uid=user_id)


def get_export_path(user_id: int) -> Path | None:
    """Return path only if file exists and has content."""
    path = _user_csv_path(user_id)
    return path if (path.exists() and path.stat().st_size > 0) else None
