"""Render Messenger messages as text: repaired text, dates, attachments, reactions, gaps."""

from __future__ import annotations

import random
import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


DEFAULT_GAP_SECONDS = 6 * 60 * 60
ANSI_RESET = "\033[0m"
ANSI_HIGHLIGHT = "\033[43;30m"
NAME_COLOR_PALETTE = [
    (231, 76, 60),
    (52, 152, 219),
    (46, 204, 113),
    (241, 196, 15),
    (155, 89, 182),
    (230, 126, 34),
    (26, 188, 156),
    (228, 87, 46),
    (142, 68, 173),
    (39, 174, 96),
    (41, 128, 185),
    (192, 57, 43),
]
ATTACHMENT_LABELS = {
    "videos": "Video",
    "gifs": "GIF",
    "audio_files": "Audio file",
    "files": "File",
}


def signature_label(signature: tuple[str, ...]) -> str:
    """Return the participants joined with " / ", or "(unknown participants)"."""
    if not signature:
        return "(unknown participants)"
    return " / ".join(signature)


def repair_text(value: str | None) -> str:
    """Undo Facebook's mojibake (UTF-8 bytes stored as Latin-1 text), up to three passes;
    "" for None or empty."""
    if not value:
        return ""

    text = value
    for _ in range(3):
        try:
            repaired = text.encode("latin-1").decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            break
        if repaired == text:
            break
        text = repaired
    return text


def format_swedish_datetime(timestamp_ms: int, tz_name: str) -> str:
    """Format a millisecond timestamp in `tz_name` as `YYYY-MM-DD HH:MM:SS`."""
    dt = datetime.fromtimestamp(timestamp_ms / 1000, tz=ZoneInfo(tz_name))
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def rgb_ansi(text: str, rgb: tuple[int, int, int], enabled: bool) -> str:
    if not enabled:
        return text
    red, green, blue = rgb
    return f"\033[38;2;{red};{green};{blue}m{text}{ANSI_RESET}"


def build_name_colors(participants: list[str], enabled: bool) -> dict[str, str]:
    if not enabled or not participants:
        return {}

    seed = sum(ord(char) for name in participants for char in name)
    palette = NAME_COLOR_PALETTE[:]
    random.Random(seed).shuffle(palette)

    return {
        name: rgb_ansi(name, palette[index % len(palette)], enabled)
        for index, name in enumerate(participants)
    }


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
            parts.append(f"{ANSI_HIGHLIGHT}{hit}{ANSI_RESET}")
        else:
            parts.append(f"[{hit}]")
        cursor = end
    parts.append(text[cursor:])
    return "".join(parts)


def format_gap(previous_timestamp_ms: int, current_timestamp_ms: int) -> str:
    """Return the gap marker between two messages, e.g. "[Gap: 2 days 3 hours]"."""
    delta_seconds = max(0, (current_timestamp_ms - previous_timestamp_ms) // 1000)
    days, remainder = divmod(delta_seconds, 24 * 60 * 60)
    hours, remainder = divmod(remainder, 60 * 60)
    minutes, seconds = divmod(remainder, 60)

    parts: list[str] = []
    if days:
        unit = "day" if days == 1 else "days"
        parts.append(f"{days} {unit}")
    if hours:
        unit = "hour" if hours == 1 else "hours"
        parts.append(f"{hours} {unit}")
    if minutes:
        unit = "minute" if minutes == 1 else "minutes"
        parts.append(f"{minutes} {unit}")
    if seconds or not parts:
        unit = "second" if seconds == 1 else "seconds"
        parts.append(f"{seconds} {unit}")

    return "[Gap: " + " ".join(parts) + "]"


def describe_attachment(message: dict) -> list[str]:
    """Return one text line per photo, video, GIF, audio file, file, sticker, share and call."""
    parts: list[str] = []

    photos = message.get("photos") or []
    if photos:
        count = len(photos)
        label = "Sent photo" if count == 1 else "Sent photos"
        parts.append(f"[{label}: {count}]")
        for item in photos:
            uri = item.get("uri", "")
            parts.append(f"[Photo ref] {repair_text(uri)}")

    for key, label in ATTACHMENT_LABELS.items():
        items = message.get(key) or []
        for item in items:
            uri = item.get("uri", "")
            parts.append(f"[Sent {label.lower()}] {repair_text(uri)}")

    sticker = message.get("sticker")
    if sticker and sticker.get("uri"):
        parts.append(f"[Sticker] {repair_text(sticker['uri'])}")

    share = message.get("share")
    if share:
        share_text = repair_text(share.get("share_text", ""))
        link = repair_text(share.get("link", ""))
        if share_text and link:
            parts.append(f"[Share] {share_text} ({link})")
        elif link:
            parts.append(f"[Share] {link}")
        elif share_text:
            parts.append(f"[Share] {share_text}")

    if message.get("call_duration") is not None:
        seconds = int(message["call_duration"])
        parts.append(f"[Call] {seconds} sec")

    return parts


def describe_reactions(message: dict) -> str:
    """Return "Reactions: actor: emoji, …", or "" without reactions."""
    reactions = message.get("reactions") or []
    if not reactions:
        return ""

    rendered = []
    for reaction in reactions:
        emoji = repair_text(reaction.get("reaction", ""))
        actor = repair_text(reaction.get("actor", "unknown"))
        rendered.append(f"{actor}: {emoji}")
    return "Reactions: " + ", ".join(rendered)


def render_message(
    message: dict,
    tz_name: str,
    name_colors: dict[str, str],
    search_terms: list[str] | None = None,
    ansi_highlight: bool = False,
) -> list[str]:
    """Return the message as text lines: "time  sender", then the content, attachments
    and reactions indented by two spaces. `name_colors` maps senders to coloured labels;
    `search_terms` highlights matches (ANSI or [brackets])."""
    sender = repair_text(message.get("sender_name", "Unknown"))
    timestamp_label = format_swedish_datetime(message["timestamp_ms"], tz_name)
    sender_label = sender
    if search_terms:
        sender_label = highlight_text(sender_label, search_terms, ansi_highlight)
        if sender_label == sender:
            sender_label = name_colors.get(sender, sender)
    else:
        sender_label = name_colors.get(sender, sender)

    lines = [f"{timestamp_label}  {sender_label}"]

    content = repair_text(message.get("content", "")).strip()
    if content:
        if search_terms:
            content = highlight_text(content, search_terms, ansi_highlight)
        lines.append(f"  {content}")

    for part in describe_attachment(message):
        if search_terms:
            part = highlight_text(part, search_terms, ansi_highlight)
        lines.append(f"  {part}")

    reactions = describe_reactions(message)
    if reactions:
        if search_terms:
            reactions = highlight_text(reactions, search_terms, ansi_highlight)
        lines.append(f"  {reactions}")

    return lines


def build_output(
    messages: list[dict],
    participants: list[str],
    tz_name: str,
    gap_seconds: int,
    use_color: bool,
    search_terms: list[str] | None = None,
    ansi_highlight: bool = False,
) -> str:

    output_lines: list[str] = []
    name_colors = build_name_colors(participants, use_color)
    if participants:
        colored_participants = [name_colors.get(name, name) for name in participants]
        output_lines.append("Chat: " + " / ".join(colored_participants))
        output_lines.append("")

    previous_timestamp_ms: int | None = None
    for message in messages:
        current_timestamp_ms = message["timestamp_ms"]
        if (
            previous_timestamp_ms is not None
            and current_timestamp_ms - previous_timestamp_ms >= gap_seconds * 1000
        ):
            output_lines.append(format_gap(previous_timestamp_ms, current_timestamp_ms))
            output_lines.append("")
        message_lines = render_message(
            message,
            tz_name,
            name_colors,
            search_terms=search_terms,
            ansi_highlight=ansi_highlight,
        )
        output_lines.extend(message_lines)
        output_lines.append("")
        previous_timestamp_ms = current_timestamp_ms

    return "\n".join(output_lines).rstrip() + "\n"


def build_info_output(
    messages: list[dict], participants: list[str], paths: list[str], tz_name: str
) -> str:
    output_lines = [
        f"Files: {len(paths)}",
        f"Messages: {len(messages)}",
    ]

    if participants:
        output_lines.append("Participants: " + ", ".join(participants))

    if messages:
        first_ts = messages[0]["timestamp_ms"]
        last_ts = messages[-1]["timestamp_ms"]
        output_lines.append(f"First message: {format_swedish_datetime(first_ts, tz_name)}")
        output_lines.append(f"Last message: {format_swedish_datetime(last_ts, tz_name)}")

    output_lines.append("Sources: " + ", ".join(Path(path).name for path in paths))
    return "\n".join(output_lines) + "\n"
