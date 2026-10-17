"""Filter Messenger messages by search terms and date range."""

from __future__ import annotations

import argparse
import re
from datetime import datetime
from zoneinfo import ZoneInfo

from export_inspector.messenger.formatting import (
    describe_attachment,
    describe_reactions,
    format_swedish_datetime,
    repair_text,
)


def term_matches_text(term: str, text: str) -> bool:
    if " " in term:
        return term in text
    if all(char.isalnum() for char in term):
        return re.search(rf"(?<!\w){re.escape(term)}\w*", text) is not None
    return term in text


def parse_from_date(value: str, tz_name: str) -> int:
    """Parse `YYYY`, `YYYY-MM` or `YYYY-MM-DD` as the start of that period in `tz_name`, in
    milliseconds. Raises argparse.ArgumentTypeError for other formats."""
    normalized = value.strip()
    try:
        if len(normalized) == 4 and normalized.isdigit():
            dt = datetime.strptime(normalized, "%Y").replace(
                month=1,
                day=1,
                tzinfo=ZoneInfo(tz_name),
            )
        elif len(normalized) == 7 and normalized[4] == "-" and normalized[:4].isdigit() and normalized[5:7].isdigit():
            dt = datetime.strptime(normalized, "%Y-%m").replace(
                day=1,
                tzinfo=ZoneInfo(tz_name),
            )
        else:
            dt = datetime.strptime(normalized, "%Y-%m-%d").replace(
                tzinfo=ZoneInfo(tz_name)
            )
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"Invalid date '{value}'. Expected format: YYYY, YYYY-MM, or YYYY-MM-DD."
        ) from exc
    return int(dt.timestamp() * 1000)


def parse_until_date(value: str, tz_name: str) -> int:
    normalized = value.strip()
    try:
        if len(normalized) == 4 and normalized.isdigit():
            year = int(normalized)
            dt = datetime(year + 1, 1, 1, tzinfo=ZoneInfo(tz_name))
        elif len(normalized) == 7 and normalized[4] == "-" and normalized[:4].isdigit() and normalized[5:7].isdigit():
            year = int(normalized[:4])
            month = int(normalized[5:7])
            if month == 12:
                dt = datetime(year + 1, 1, 1, tzinfo=ZoneInfo(tz_name))
            else:
                dt = datetime(year, month + 1, 1, tzinfo=ZoneInfo(tz_name))
        else:
            year, month, day = map(int, normalized.split("-"))
            dt = datetime(year, month, day, tzinfo=ZoneInfo(tz_name))
            dt = dt.replace(hour=23, minute=59, second=59, microsecond=999000)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"Invalid date '{value}'. Expected format: YYYY, YYYY-MM, or YYYY-MM-DD."
        ) from exc
    return int(dt.timestamp() * 1000)


def build_message_search_texts(message: dict, tz_name: str) -> list[str]:
    sender = repair_text(message.get("sender_name", "Unknown")).strip()
    texts = [sender, format_swedish_datetime(message["timestamp_ms"], tz_name)]

    content = repair_text(message.get("content", "")).strip()
    if content:
        texts.append(content)

    texts.extend(describe_attachment(message))

    reactions = describe_reactions(message)
    if reactions:
        texts.append(reactions)

    return texts


def filter_messages_search(
    messages: list[dict],
    search_terms: list[str],
    tz_name: str,
    match_any: bool,
) -> list[dict]:
    if not search_terms:
        return messages

    filtered: list[dict] = []
    for message in messages:
        texts = [text.lower() for text in build_message_search_texts(message, tz_name)]
        if match_any:
            if any(any(term_matches_text(term, text) for text in texts) for term in search_terms):
                filtered.append(message)
        else:
            if all(any(term_matches_text(term, text) for text in texts) for term in search_terms):
                filtered.append(message)
    return filtered


def filter_messages_from(messages: list[dict], from_timestamp_ms: int | None) -> list[dict]:
    """Keep messages at or after `from_timestamp_ms`; all of them for None."""
    if from_timestamp_ms is None:
        return messages
    return [message for message in messages if message["timestamp_ms"] >= from_timestamp_ms]


def filter_messages_until(messages: list[dict], until_timestamp_ms: int | None) -> list[dict]:
    if until_timestamp_ms is None:
        return messages
    return [message for message in messages if message["timestamp_ms"] <= until_timestamp_ms]


def message_search_blob(message: dict, timezone_name: str) -> str:
    """Return the lowercased text the GUI's live filter matches against: sender, content,
    time, attachments and reactions."""
    values: list[str] = [
        repair_text(message.get("sender_name", "")),
        repair_text(message.get("content", "")),
        format_swedish_datetime(message["timestamp_ms"], timezone_name),
    ]
    values.extend(describe_attachment(message))
    reactions = describe_reactions(message)
    if reactions:
        values.append(reactions)
    return "\n".join(values).lower()


def filter_messages_text(messages: list[dict], query: str, timezone_name: str) -> list[dict]:
    """Keep messages whose `message_search_blob` contains every whitespace-separated term
    of `query` (case-insensitive substring match); all messages for an empty query.

    This is the GUI's live filter. The CLI's `filter_messages_search` matches per field
    with `term_matches_text` and supports any-term matching instead.
    """
    query = query.strip().lower()
    if not query:
        return messages
    terms = query.split()
    matches: list[dict] = []
    for message in messages:
        blob = message_search_blob(message, timezone_name)
        if all(term in blob for term in terms):
            matches.append(message)
    return matches
