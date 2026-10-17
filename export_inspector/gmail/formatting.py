"""Gmail output: the CLI's info and search result printing, and full message text."""

from __future__ import annotations

from collections import Counter
from pathlib import Path

from export_inspector.gmail.mbox import decode_header_value, format_date, parse_date
from export_inspector.gmail.models import MailboxStats, SearchResult

ANSI_RESET = "\033[0m"
ANSI_HIGHLIGHT = "\033[1;30;43m"


def print_info(
    path: Path,
    stats: MailboxStats,
    sender_counts: Counter[str],
    recipient_counts: Counter[str],
    subject_counts: Counter[str],
    top: int,
    timezone: str,
    has_mime_stats: bool,
) -> None:
    """Print the `info` command's mailbox summary and top senders/recipients/subjects."""
    print(f"File: {path}")
    print(f"Messages: {stats.total_messages}")
    print(
        f"Date range: {format_date(stats.first_dt, timezone)} to "
        f"{format_date(stats.last_dt, timezone)}"
    )
    if has_mime_stats:
        print(f"Multipart messages: {stats.multipart_messages}")
        print(f"Messages with attachments: {stats.attachment_messages}")
        print(f"Attachment files: {stats.attachment_files}")
    else:
        print("Multipart messages: n/a (not stored in this index)")
        print("Messages with attachments: n/a (not stored in this index)")
        print("Attachment files: n/a (not stored in this index)")

    print()
    print(f"Top senders ({top}):")
    for sender, count in sender_counts.most_common(top):
        print(f"  {count:>6}  {sender}")

    print()
    print(f"Top recipients ({top}):")
    for recipient, count in recipient_counts.most_common(top):
        print(f"  {count:>6}  {recipient}")

    print()
    print(f"Top subjects ({top}):")
    for subject, count in subject_counts.most_common(top):
        print(f"  {count:>6}  {subject}")


def print_results(results: list[SearchResult]) -> None:
    """Print search results for the terminal, or "No matches found."."""
    if not results:
        print("No matches found.")
        return
    for result in results:
        print(f"{result.index}. {result.date_text}")
        print(f"   From: {result.sender}")
        if result.to_text:
            print(f"   To: {result.to_text}")
        print(f"   Subject: {result.subject}")
        if result.labels:
            print(f"   Labels: {result.labels}")
        if result.thread_id:
            print(f"   Thread: {result.thread_id}")
        print(f"   Snippet: {result.snippet}")
        print()


def format_full_message(headers: dict[str, str], body_text: str, timezone: str) -> str:
    """Return a message as text: Date/From/To/Cc/Subject/Labels/Thread/Message-Id headers
    (empty ones left out), a blank line and the decoded body."""
    sender = decode_header_value(headers.get("from")) or "unknown"
    recipients = decode_header_value(headers.get("to"))
    cc_text = decode_header_value(headers.get("cc"))
    subject = decode_header_value(headers.get("subject")) or "(no subject)"
    labels = decode_header_value(headers.get("x-gmail-labels"))
    thread_id = headers.get("x-gm-thrid", "")
    message_id = decode_header_value(headers.get("message-id"))
    parsed_date = parse_date(headers.get("date"))
    lines = [
        f"Date: {format_date(parsed_date, timezone)}",
        f"From: {sender}",
    ]
    if recipients:
        lines.append(f"To: {recipients}")
    if cc_text:
        lines.append(f"Cc: {cc_text}")
    lines.append(f"Subject: {subject}")
    if labels:
        lines.append(f"Labels: {labels}")
    if thread_id:
        lines.append(f"Thread: {thread_id}")
    if message_id:
        lines.append(f"Message-Id: {message_id}")
    lines.append("")
    lines.append(body_text or "(no decoded body text)")
    return "\n".join(lines)
