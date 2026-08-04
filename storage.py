"""
utils/storage.py — CSV persistence for search results.
Each user gets their own CSV files so /export returns only their results.
Thread-safe via asyncio-friendly aiofiles.

Supports both Person search results and Company information storage.
"""
from __future__ import annotations
import csv
from io import StringIO
from pathlib import Path
from logger import log
import aiofiles
from config import settings
from models import Person, CompanyInfo
from logger import log

# Person search results CSV columns
_PERSON_HEADERS = ["name", "title", "company", "linkedin_url", "confidence", "timestamp"]

# Company information CSV columns
_COMPANY_HEADERS = ["company_name", "company_url", "industry", "headcount", "location", "confidence", "timestamp"]


def _user_csv_path(user_id: int, data_type: str = "person") -> Path:
    """Get the CSV path for a user's specific data type.
    
    Args:
        user_id: Telegram user ID
        data_type: "person" or "company" to determine file name
    
    Returns:
        Path object for the CSV file
    """
    filename = f"results_{user_id}_{data_type}.csv"
    return settings.DATA_DIR / filename


async def append_results(user_id: int, people: list[Person]) -> None:
    """Append person search results to the user's CSV, creating the file if needed.
    
    Args:
        user_id: Telegram user ID
        people: List of Person objects to append
    """
    if not people:
        return
    
    path = _user_csv_path(user_id, "person")
    file_exists = path.exists()
    
    # Build CSV rows in memory first
    buf = StringIO()
    writer = csv.DictWriter(buf, fieldnames=_PERSON_HEADERS)
    
    if not file_exists:
        writer.writeheader()
    
    for person in people:
        writer.writerow(person.as_csv_row())
    
    # Write asynchronously
    async with aiofiles.open(path, mode="a", newline="", encoding="utf-8") as f:
        await f.write(buf.getvalue())
    
    log.debug("Appended {n} person rows to {path}", n=len(people), path=path)


async def append_company_results(user_id: int, companies: list[CompanyInfo]) -> None:
    """Append company search results to the user's CSV, creating the file if needed.
    
    Args:
        user_id: Telegram user ID
        companies: List of CompanyInfo objects to append
    """
    if not companies:
        return
    
    path = _user_csv_path(user_id, "company")
    file_exists = path.exists()
    
    # Build CSV rows in memory first
    buf = StringIO()
    writer = csv.DictWriter(buf, fieldnames=_COMPANY_HEADERS)
    
    if not file_exists:
        writer.writeheader()
    
    for company in companies:
        writer.writerow(company.as_csv_row())
    
    # Write asynchronously
    async with aiofiles.open(path, mode="a", newline="", encoding="utf-8") as f:
        await f.write(buf.getvalue())
    
    log.debug("Appended {n} company rows to {path}", n=len(companies), path=path)


async def read_all_results(user_id: int, data_type: str = "person") -> list[dict]:
    """Return all stored rows for a user as a list of dicts.
    
    Args:
        user_id: Telegram user ID
        data_type: "person" or "company" to specify which CSV to read
    
    Returns:
        List of dictionaries representing CSV rows
    """
    path = _user_csv_path(user_id, data_type)
    
    if not path.exists():
        return []
    
    async with aiofiles.open(path, mode="r", encoding="utf-8") as f:
        content = await f.read()
    
    reader = csv.DictReader(StringIO(content))
    return list(reader)


async def read_person_results(user_id: int) -> list[dict]:
    """Convenience function to read person search results."""
    return await read_all_results(user_id, "person")


async def read_company_results(user_id: int) -> list[dict]:
    """Convenience function to read company search results."""
    return await read_all_results(user_id, "company")


async def clear_results(user_id: int, data_type: str = "all") -> None:
    """Delete a user's CSV files (used in tests / admin reset).
    
    Args:
        user_id: Telegram user ID
        data_type: "person", "company", or "all" to clear specific or all files
    """
    if data_type == "all":
        for dtype in ["person", "company"]:
            path = _user_csv_path(user_id, dtype)
            if path.exists():
                path.unlink()
                log.info("Cleared {dtype} results for user {uid}", dtype=dtype, uid=user_id)
    else:
        path = _user_csv_path(user_id, data_type)
        if path.exists():
            path.unlink()
            log.info("Cleared {dtype} results for user {uid}", dtype=data_type, uid=user_id)


def get_export_path(user_id: int, data_type: str = "person") -> Path | None:
    """Return path only if file exists and has content.
    
    Args:
        user_id: Telegram user ID
        data_type: "person" or "company" file type
    
    Returns:
        Path object if file exists and has content, None otherwise
    """
    path = _user_csv_path(user_id, data_type)
    return path if (path.exists() and path.stat().st_size > 0) else None


async def get_user_export_summary(user_id: int) -> dict:
    """Get summary of available exports for a user.
    
    Returns:
        Dict with counts of person and company results
    """
    person_results = await read_person_results(user_id)
    company_results = await read_company_results(user_id)
    
    return {
        "person_count": len(person_results),
        "company_count": len(company_results),
        "total_count": len(person_results) + len(company_results),
        "person_path": get_export_path(user_id, "person"),
        "company_path": get_export_path(user_id, "company"),
    }
