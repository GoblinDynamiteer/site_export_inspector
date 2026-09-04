from __future__ import annotations

import argparse
import email.header
import email.parser
import email.policy
import email.utils
import html
import quopri
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Iterable
from zoneinfo import ZoneInfo

from export_inspector.gmail.models import MailboxStats, SearchResult


PROGRESS_EVERY = 10000
SNIPPET_LIMIT = 220
BASE64_CHARS = set(
    b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/="
)


def decode_header_value(value: str | None) -> str:
    if not value:
        return ""
    decoded_parts: list[str] = []
    for chunk, encoding in email.header.decode_header(value):
        if isinstance(chunk, bytes):
            for candidate_encoding in (encoding, "utf-8", "latin-1"):
                if not candidate_encoding:
                    continue
                try:
                    decoded_parts.append(
                        chunk.decode(candidate_encoding, errors="replace")
                    )
                    break
                except LookupError:
                    continue
            else:
                decoded_parts.append(chunk.decode("utf-8", errors="replace"))
        else:
            decoded_parts.append(chunk)
    return "".join(decoded_parts).strip()


def extract_people(values: Iterable[str]) -> list[str]:
    decoded_values = [decode_header_value(value) for value in values if value]
    people: list[str] = []
    for _, address in email.utils.getaddresses(decoded_values):
        people.append(address or "unknown")
    return people


def extract_addresses(*values: str) -> str:
    decoded_values = [decode_header_value(value) for value in values if value]
    addresses = [
        address or "unknown"
        for _, address in email.utils.getaddresses(decoded_values)
    ]
    return ", ".join(addresses)


def parse_headers(header_lines: list[bytes]) -> dict[str, str]:
    unfolded: list[bytes] = []
    current = b""
    for raw_line in header_lines:
        line = raw_line.rstrip(b"\r\n")
        if not line:
            continue
        if line[:1] in (b" ", b"\t") and current:
            current += b" " + line.lstrip()
            continue
        if current:
            unfolded.append(current)
        current = line
    if current:
        unfolded.append(current)

    headers: dict[str, str] = {}
    for line in unfolded:
        if b":" not in line:
            continue
        key, value = line.split(b":", 1)
        headers[key.decode("utf-8", errors="replace").lower()] = value.decode(
            "utf-8", errors="replace"
        ).strip()
    return headers


def parse_date(date_header: str | None) -> datetime | None:
    if not date_header:
        return None
    try:
        parsed_date = email.utils.parsedate_to_datetime(date_header)
    except ValueError:
        try:
            parsed_date = datetime.fromisoformat(date_header)
        except ValueError:
            return None
    if parsed_date is None:
        return None
    if parsed_date.tzinfo is None:
        parsed_date = parsed_date.replace(tzinfo=ZoneInfo("UTC"))
    return parsed_date


def shorten(text: str, limit: int = SNIPPET_LIMIT) -> str:
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3] + "..."


def looks_like_encoded_blob(raw_line: bytes) -> bool:
    stripped = raw_line.strip()
    if len(stripped) < 80:
        return False
    if b" " in stripped or b"\t" in stripped:
        return False
    return all(byte in BASE64_CHARS for byte in stripped)


def line_text_candidates(raw_line: bytes) -> list[str]:
    stripped = raw_line.strip()
    if not stripped or looks_like_encoded_blob(stripped):
        return []

    candidates: list[str] = []
    decoded = stripped.decode("utf-8", errors="replace")
    candidates.append(decoded)

    qp_decoded = quopri.decodestring(stripped)
    qp_text = qp_decoded.decode("utf-8", errors="replace")
    if qp_text != decoded:
        candidates.append(qp_text)

    return candidates


def consume_body_line(
    raw_line: bytes,
    pending_qp_line: bytes,
) -> tuple[list[str], bytes]:
    stripped = raw_line.rstrip(b"\r\n")
    if pending_qp_line:
        stripped = pending_qp_line + stripped
        pending_qp_line = b""

    # Quoted-printable soft line breaks often split words across lines, which can
    # create false matches like "b=\norder-collapse" for the search term "order".
    if stripped.endswith(b"="):
        return [], stripped[:-1]

    return line_text_candidates(stripped), pending_qp_line


def choose_text_candidate(candidates: list[str]) -> str:
    if not candidates:
        return ""
    for candidate in candidates:
        compact = " ".join(candidate.split())
        if compact:
            return compact
    return ""


def parse_date_filter(value: str | None, tz_name: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=ZoneInfo(tz_name))
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"Invalid date '{value}'. Expected format: YYYY-MM-DD."
        ) from exc


def format_date(dt: datetime | None, tz_name: str) -> str:
    if dt is None:
        return "n/a"
    return dt.astimezone(ZoneInfo(tz_name)).strftime("%Y-%m-%d %H:%M:%S")


def use_ansi(args: argparse.Namespace) -> bool:
    return sys.stdout.isatty() and not getattr(args, "no_ansi", False)


def term_matches_text(term: str, text: str) -> bool:
    if " " in term:
        return term in text
    if all(char.isalnum() for char in term):
        return re.search(rf"(?<!\w){re.escape(term)}\w*", text) is not None
    return term in text


def highlight_text(text: str, terms: list[str], ansi_enabled: bool) -> str:
    if not text:
        return text

    matches: list[tuple[int, int]] = []
    lowered = text.lower()
    for term in sorted({term for term in terms if term}, key=len, reverse=True):
        if " " in term:
            pattern = re.escape(term)
        elif all(char.isalnum() for char in term):
            pattern = rf"(?<!\w){re.escape(term)}\w*"
        else:
            pattern = re.escape(term)
        for match in re.finditer(pattern, lowered):
            matches.append((match.start(), match.end()))

    if not matches:
        return text

    matches.sort()
    merged: list[tuple[int, int]] = []
    for start, end in matches:
        if not merged or start > merged[-1][1]:
            merged.append((start, end))
        else:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))

    parts: list[str] = []
    cursor = 0
    for start, end in merged:
        parts.append(text[cursor:start])
        hit = text[start:end]
        if ansi_enabled:
            parts.append(f"\033[1;30;43m{hit}\033[0m")
        else:
            parts.append(f"[{hit}]")
        cursor = end
    parts.append(text[cursor:])
    return "".join(parts)


def terms_match_in_texts(
    terms: list[str],
    texts: list[str],
    match_any: bool,
) -> tuple[set[str], str | None]:
    matched: set[str] = set()
    snippet: str | None = None
    for text in texts:
        lowered = text.lower()
        line_matched = [term for term in terms if term_matches_text(term, lowered)]
        if not line_matched:
            continue
        matched.update(line_matched)
        if snippet is None:
            snippet = shorten(text)
        if match_any:
            break
    return matched, snippet


def update_date_range(stats: MailboxStats, date_header: str | None) -> None:
    parsed_date = parse_date(date_header)
    if parsed_date is None:
        return
    if stats.first_dt is None or parsed_date < stats.first_dt:
        stats.first_dt = parsed_date
    if stats.last_dt is None or parsed_date > stats.last_dt:
        stats.last_dt = parsed_date


def finalize_info_message(
    headers: dict[str, str],
    attachment_count: int,
    stats: MailboxStats,
    sender_counts: Counter[str],
    recipient_counts: Counter[str],
    subject_counts: Counter[str],
) -> None:
    if not headers:
        return

    stats.total_messages += 1

    sender = extract_people([headers.get("from", "")])
    sender_counts[sender[0] if sender else "unknown"] += 1

    recipients = extract_people(
        [headers.get("to", ""), headers.get("cc", ""), headers.get("bcc", "")]
    )
    for recipient in recipients:
        if recipient and recipient != "unknown":
            recipient_counts[recipient] += 1

    subject = decode_header_value(headers.get("subject")) or "(no subject)"
    subject_counts[subject] += 1

    update_date_range(stats, headers.get("date"))

    content_type = headers.get("content-type", "").lower()
    if content_type.startswith("multipart/"):
        stats.multipart_messages += 1

    if attachment_count > 0:
        stats.attachment_messages += 1
        stats.attachment_files += attachment_count


def scan_mbox_info(
    path: Path,
    show_progress: bool,
) -> tuple[MailboxStats, Counter[str], Counter[str], Counter[str]]:
    """Scan a raw Gmail `.mbox` file and return aggregate mailbox statistics.

    The scan reads the mailbox sequentially without decoding full message bodies.
    It returns mailbox counters plus top-level sender, recipient, and subject
    counters. When `show_progress` is true, progress is written to stderr every
    `PROGRESS_EVERY` messages.
    """

    stats = MailboxStats()
    sender_counts: Counter[str] = Counter()
    recipient_counts: Counter[str] = Counter()
    subject_counts: Counter[str] = Counter()

    current_header_lines: list[bytes] = []
    current_headers: dict[str, str] = {}
    attachment_count = 0
    in_headers = False
    have_message = False
    pending_disposition = b""
    pending_attachment_counted = False

    with path.open("rb") as handle:
        for raw_line in handle:
            if raw_line.startswith(b"From "):
                if have_message:
                    finalize_info_message(
                        current_headers,
                        attachment_count,
                        stats,
                        sender_counts,
                        recipient_counts,
                        subject_counts,
                    )
                    if show_progress and stats.total_messages % PROGRESS_EVERY == 0:
                        print(
                            f"Scanned {stats.total_messages} messages...",
                            file=sys.stderr,
                            flush=True,
                        )

                current_header_lines = []
                current_headers = {}
                attachment_count = 0
                in_headers = True
                have_message = True
                pending_disposition = b""
                pending_attachment_counted = False
                continue

            if not have_message:
                continue

            if in_headers:
                if raw_line in (b"\n", b"\r\n"):
                    current_headers = parse_headers(current_header_lines)
                    in_headers = False
                    continue
                current_header_lines.append(raw_line)
                continue

            lower_line = raw_line.lower().rstrip(b"\r\n")
            if lower_line.startswith(b"content-disposition:"):
                pending_disposition = lower_line
                pending_attachment_counted = False
                if b"attachment" in pending_disposition:
                    attachment_count += 1
                    pending_attachment_counted = True
                continue

            if pending_disposition and raw_line[:1] in (b" ", b"\t"):
                pending_disposition += b" " + lower_line.lstrip()
                if (
                    b"attachment" in pending_disposition
                    and not pending_attachment_counted
                ):
                    attachment_count += 1
                    pending_attachment_counted = True
                continue

            pending_disposition = b""
            pending_attachment_counted = False

    if have_message:
        finalize_info_message(
            current_headers,
            attachment_count,
            stats,
            sender_counts,
            recipient_counts,
            subject_counts,
        )

    return stats, sender_counts, recipient_counts, subject_counts


def build_header_search_fields(headers: dict[str, str]) -> list[tuple[str, str]]:
    fields = [
        ("From", decode_header_value(headers.get("from"))),
        ("To", decode_header_value(headers.get("to"))),
        ("Cc", decode_header_value(headers.get("cc"))),
        ("Subject", decode_header_value(headers.get("subject"))),
        ("Labels", decode_header_value(headers.get("x-gmail-labels"))),
    ]
    return [(name, value) for name, value in fields if value]


def message_passes_filters(
    headers: dict[str, str],
    parsed_date: datetime | None,
    args: argparse.Namespace,
) -> bool:
    sender = decode_header_value(headers.get("from")).lower()
    recipients = " ".join(
        [
            decode_header_value(headers.get("to")).lower(),
            decode_header_value(headers.get("cc")).lower(),
            decode_header_value(headers.get("bcc")).lower(),
        ]
    )
    subject = decode_header_value(headers.get("subject")).lower()
    labels = decode_header_value(headers.get("x-gmail-labels")).lower()

    if args.from_filter and args.from_filter.lower() not in sender:
        return False
    if args.to_filter and args.to_filter.lower() not in recipients:
        return False
    if args.subject_filter and args.subject_filter.lower() not in subject:
        return False
    if args.label_filter and args.label_filter.lower() not in labels:
        return False

    after_dt = parse_date_filter(args.after, args.timezone)
    before_dt = parse_date_filter(args.before, args.timezone)
    if after_dt and (
        parsed_date is None or parsed_date.astimezone(after_dt.tzinfo) < after_dt
    ):
        return False
    if before_dt and (
        parsed_date is None or parsed_date.astimezone(before_dt.tzinfo) >= before_dt
    ):
        return False

    return True


def finalize_search_message(
    index: int,
    headers: dict[str, str],
    body_match_terms: set[str],
    body_snippet: str | None,
    args: argparse.Namespace,
) -> SearchResult | None:
    if not headers:
        return None

    parsed_date = parse_date(headers.get("date"))
    if not message_passes_filters(headers, parsed_date, args):
        return None

    sender = decode_header_value(headers.get("from")) or "unknown"
    to_text = decode_header_value(headers.get("to"))
    subject = decode_header_value(headers.get("subject")) or "(no subject)"
    labels = decode_header_value(headers.get("x-gmail-labels"))
    thread_id = headers.get("x-gm-thrid", "")

    query_terms = [term.lower() for term in args.terms]
    if not query_terms:
        matched_enough = True
        snippet = body_snippet or shorten(subject)
    else:
        header_fields = build_header_search_fields(headers)
        header_texts = [f"{name}: {value}" for name, value in header_fields]
        header_matches, header_snippet = terms_match_in_texts(
            query_terms, header_texts, args.any
        )
        matched_terms = set(header_matches)
        matched_terms.update(body_match_terms)
        matched_enough = (
            bool(matched_terms) if args.any else len(matched_terms) == len(query_terms)
        )
        snippet = header_snippet or body_snippet or shorten(subject)

    if not matched_enough:
        return None

    return SearchResult(
        index=index,
        date_text=format_date(parsed_date, args.timezone),
        sender=sender,
        to_text=to_text,
        subject=subject,
        labels=labels,
        thread_id=thread_id,
        snippet=highlight_text(snippet, query_terms, use_ansi(args)),
    )


def search_mbox(args: argparse.Namespace) -> list[SearchResult]:
    """Search a raw Gmail `.mbox` file using the CLI search namespace contract.

    Header filters are applied for every message. Body scanning is skipped for
    `--headers-only` searches and stops early once the query has matched enough
    terms. The returned results preserve the raw mailbox message indexes used by
    `google-mail show`.
    """

    path = Path(args.input_file)
    results: list[SearchResult] = []

    current_header_lines: list[bytes] = []
    current_headers: dict[str, str] = {}
    in_headers = False
    have_message = False
    index = 0

    query_terms = [term.lower() for term in args.terms]
    current_body_match_terms: set[str] = set()
    current_body_snippet: str | None = None
    current_need_body_scan = False
    pending_qp_line = b""

    with path.open("rb") as handle:
        for raw_line in handle:
            if raw_line.startswith(b"From "):
                if have_message:
                    index += 1
                    result = finalize_search_message(
                        index,
                        current_headers,
                        current_body_match_terms,
                        current_body_snippet,
                        args,
                    )
                    if result:
                        results.append(result)
                        if len(results) >= args.limit:
                            return results
                    if not args.no_progress and index % PROGRESS_EVERY == 0:
                        print(
                            f"Scanned {index} messages...",
                            file=sys.stderr,
                            flush=True,
                        )

                current_header_lines = []
                current_headers = {}
                current_body_match_terms = set()
                current_body_snippet = None
                current_need_body_scan = bool(query_terms) and not args.headers_only
                pending_qp_line = b""
                in_headers = True
                have_message = True
                continue

            if not have_message:
                continue

            if in_headers:
                if raw_line in (b"\n", b"\r\n"):
                    current_headers = parse_headers(current_header_lines)
                    in_headers = False
                    continue
                current_header_lines.append(raw_line)
                continue

            if not current_need_body_scan or not query_terms:
                continue

            candidates, pending_qp_line = consume_body_line(raw_line, pending_qp_line)
            if not candidates:
                continue
            matched_terms, snippet = terms_match_in_texts(
                query_terms, candidates, args.any
            )
            if matched_terms:
                current_body_match_terms.update(matched_terms)
                if current_body_snippet is None and snippet:
                    current_body_snippet = snippet
                if args.any or len(current_body_match_terms) == len(query_terms):
                    current_need_body_scan = False

    if have_message:
        index += 1
        result = finalize_search_message(
            index,
            current_headers,
            current_body_match_terms,
            current_body_snippet,
            args,
        )
        if result:
            results.append(result)

    return results


def collect_message_body_text(body_lines: list[bytes]) -> str:
    parts: list[str] = []
    pending_qp_line = b""
    for raw_line in body_lines:
        candidates, pending_qp_line = consume_body_line(raw_line, pending_qp_line)
        text = choose_text_candidate(candidates)
        if text:
            parts.append(text)
    if pending_qp_line:
        text = choose_text_candidate(line_text_candidates(pending_qp_line))
        if text:
            parts.append(text)
    return "\n".join(parts).strip()


def html_to_text(value: str) -> str:
    text = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", value)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</p\s*>", "\n\n", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = html.unescape(text)
    lines = [line.strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line).strip()


def decode_payload(payload: bytes, charset: str | None) -> str:
    for candidate in (charset, "utf-8", "latin-1"):
        if not candidate:
            continue
        try:
            return payload.decode(candidate, errors="replace")
        except LookupError:
            continue
    return payload.decode("utf-8", errors="replace")


def extract_message_body(message) -> str:
    plain_parts: list[str] = []
    html_parts: list[str] = []

    for part in message.walk():
        if part.get_content_disposition() == "attachment":
            continue
        if part.get_content_maintype() != "text":
            continue

        payload = part.get_payload(decode=True)
        if payload is None:
            raw_payload = part.get_payload()
            if isinstance(raw_payload, str):
                text = raw_payload
            else:
                continue
        else:
            text = decode_payload(payload, part.get_content_charset())

        subtype = part.get_content_subtype().lower()
        if subtype == "plain":
            plain_parts.append(text)
        elif subtype == "html":
            html_parts.append(html_to_text(text))

    if plain_parts:
        return "\n\n".join(part.strip() for part in plain_parts if part.strip()).strip()
    if html_parts:
        return "\n\n".join(part.strip() for part in html_parts if part.strip()).strip()
    return ""


def parse_message_bytes(message_bytes: bytes) -> tuple[dict[str, str], str]:
    message = email.parser.BytesParser(policy=email.policy.default).parsebytes(
        message_bytes
    )
    headers = {
        key.lower(): str(value)
        for key, value in message.items()
    }
    body_text = extract_message_body(message)
    return headers, body_text


def load_message_from_mbox(
    path: Path,
    target_index: int,
    show_progress: bool,
) -> tuple[dict[str, str], str]:
    """Load one decoded message body from a raw Gmail `.mbox` by message index.

    `target_index` is the one-based index shown by raw search results. The file
    is scanned sequentially and raises `SystemExit` if the requested message is
    missing. When `show_progress` is true, progress is written to stderr every
    `PROGRESS_EVERY` messages.
    """

    current_header_lines: list[bytes] = []
    current_body_lines: list[bytes] = []
    in_headers = False
    have_message = False
    index = 0

    with path.open("rb") as handle:
        for raw_line in handle:
            if raw_line.startswith(b"From "):
                if have_message:
                    index += 1
                    if index == target_index:
                        message_bytes = (
                            b"".join(current_header_lines)
                            + b"\n"
                            + b"".join(current_body_lines)
                        )
                        return parse_message_bytes(message_bytes)
                    if show_progress and index % PROGRESS_EVERY == 0:
                        print(
                            f"Scanned {index} messages...",
                            file=sys.stderr,
                            flush=True,
                        )

                current_header_lines = []
                current_body_lines = []
                in_headers = True
                have_message = True
                continue

            if not have_message:
                continue

            if in_headers:
                if raw_line in (b"\n", b"\r\n"):
                    in_headers = False
                    continue
                current_header_lines.append(raw_line)
                continue

            current_body_lines.append(raw_line)

    if have_message:
        index += 1
        if index == target_index:
            message_bytes = b"".join(current_header_lines) + b"\n" + b"".join(
                current_body_lines
            )
            return parse_message_bytes(message_bytes)

    raise SystemExit(f"Message index not found: {target_index}")


def load_message_from_offset(path: Path, source_offset: int) -> tuple[dict[str, str], str]:
    """Load one decoded message from a Gmail `.mbox` source byte offset.

    Offsets are produced by the SQLite indexing service. Invalid offsets raise
    `SystemExit`; successful loads return lower-cased message headers and the
    decoded text body.
    """

    with path.open("rb") as handle:
        handle.seek(source_offset)
        first_line = handle.readline()
        if not first_line.startswith(b"From "):
            raise SystemExit(f"Invalid message offset in index: {source_offset}")

        message_lines: list[bytes] = []
        while True:
            position = handle.tell()
            raw_line = handle.readline()
            if not raw_line:
                break
            if raw_line.startswith(b"From "):
                handle.seek(position)
                break
            message_lines.append(raw_line)

    return parse_message_bytes(b"".join(message_lines))
