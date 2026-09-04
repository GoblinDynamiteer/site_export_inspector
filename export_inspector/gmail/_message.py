from __future__ import annotations

import email.header
import email.utils
import quopri
from datetime import datetime
from typing import Iterable
from zoneinfo import ZoneInfo


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
