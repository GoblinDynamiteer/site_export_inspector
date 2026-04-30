#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import random
import re
import sys
import termios
import tty
from datetime import datetime
from pathlib import Path
import zipfile
from zoneinfo import ZoneInfo


DEFAULT_GAP_SECONDS = 6 * 60 * 60
ANSI_RESET = "\033[0m"
ANSI_CLEAR_LINE = "\r\033[2K"
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


def participant_signature_from_data(data: dict) -> tuple[str, ...]:
    names: set[str] = set()
    for participant in data.get("participants", []):
        if isinstance(participant, str):
            name = repair_text(participant).strip()
        else:
            name = repair_text(participant.get("name", "")).strip()
        if name:
            names.add(name)
    return tuple(sorted(names))


def participant_signature_from_message(message: dict) -> tuple[str, ...]:
    sender = repair_text(message.get("sender_name", "")).strip()
    return (sender,) if sender else ()


def message_sort_key(message: dict) -> tuple[int, str, str]:
    return (
        int(message.get("timestamp_ms", 0)),
        repair_text(message.get("sender_name", "")).strip(),
        repair_text(message.get("content", "")).strip(),
    )


def message_dedupe_key(message: dict) -> tuple:
    attachments: list[tuple[str, str]] = []
    for key in ("photos", "videos", "gifs", "audio_files", "files"):
        for item in message.get(key) or []:
            attachments.append((key, repair_text(item.get("uri", "")).strip()))

    sticker = ""
    if message.get("sticker"):
        sticker = repair_text((message.get("sticker") or {}).get("uri", "")).strip()

    share = message.get("share") or {}
    share_key = (
        repair_text(share.get("link", "")).strip(),
        repair_text(share.get("share_text", "")).strip(),
    )

    reactions = tuple(
        sorted(
            (
                repair_text(reaction.get("actor", "")).strip(),
                repair_text(reaction.get("reaction", "")).strip(),
            )
            for reaction in (message.get("reactions") or [])
        )
    )

    return (
        int(message.get("timestamp_ms", 0)),
        repair_text(message.get("sender_name", "")).strip(),
        repair_text(message.get("content", "")).strip(),
        tuple(sorted(attachments)),
        sticker,
        share_key,
        int(message.get("call_duration") or 0),
        reactions,
    )


def is_messenger_thread_json_path(path_text: str) -> bool:
    lower = path_text.lower().replace("\\", "/")
    file_name = Path(lower).name
    if "/your_facebook_activity/messages/" in lower:
        return file_name.startswith("message_") and file_name.endswith(".json")
    if "/" not in lower.strip("/") and file_name.endswith(".json") and "_" in file_name:
        return True
    return False


def normalize_message(message: dict) -> dict:
    if "timestamp_ms" in message:
        return message

    normalized: dict = {
        "timestamp_ms": int(message.get("timestamp", 0)),
        "sender_name": repair_text(message.get("senderName", "Unknown")).strip() or "Unknown",
        "content": repair_text(message.get("text", "")).strip(),
    }

    media = message.get("media") or []
    if media:
        normalized["files"] = [
            {"uri": repair_text(item.get("uri", "")).strip()}
            for item in media
            if repair_text(item.get("uri", "")).strip()
        ]

    reactions = message.get("reactions") or []
    if reactions:
        normalized["reactions"] = [
            {
                "actor": repair_text(reaction.get("actor", "")).strip(),
                "reaction": repair_text(reaction.get("reaction", "")).strip(),
            }
            for reaction in reactions
        ]

    if message.get("isUnsent") and not normalized["content"]:
        normalized["content"] = "[Message unsent]"

    return normalized


def load_json_thread(path: Path) -> tuple[list[dict], tuple[str, ...]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    messages = [normalize_message(message) for message in data.get("messages", [])]
    return messages, participant_signature_from_data(data)


def load_zip_thread_members(
    path: Path,
    target_signatures: set[tuple[str, ...]],
) -> tuple[list[tuple[str, list[dict]]], set[tuple[str, ...]]]:
    matched_threads: list[tuple[str, list[dict]]] = []
    seen_signatures: set[tuple[str, ...]] = set()

    with zipfile.ZipFile(path) as archive:
        for member_name in sorted(archive.namelist()):
            if not is_messenger_thread_json_path(member_name):
                continue
            try:
                data = json.loads(archive.read(member_name).decode("utf-8"))
            except Exception:
                continue
            if not isinstance(data, dict) or "participants" not in data or "messages" not in data:
                continue
            signature = participant_signature_from_data(data)
            if target_signatures and signature not in target_signatures:
                continue
            seen_signatures.add(signature)
            matched_threads.append(
                (
                    member_name,
                    [normalize_message(message) for message in data.get("messages", [])],
                )
            )

    return matched_threads, seen_signatures


def discover_folder_sources(folder: Path) -> tuple[list[Path], list[Path], set[tuple[str, ...]]]:
    json_paths = sorted(path for path in folder.rglob("message_*.json") if path.is_file())
    zip_paths = sorted(path for path in folder.rglob("*.zip") if path.is_file())

    target_signatures: set[tuple[str, ...]] = set()
    for path in json_paths:
        try:
            _messages, signature = load_json_thread(path)
        except Exception:
            continue
        if signature:
            target_signatures.add(signature)

    return json_paths, zip_paths, target_signatures


def repair_text(value: str | None) -> str:
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
            parts.append(f"{ANSI_HIGHLIGHT}{hit}{ANSI_RESET}")
        else:
            parts.append(f"[{hit}]")
        cursor = end
    parts.append(text[cursor:])
    return "".join(parts)


def read_pager_action(prompt: str) -> str:
    print(prompt, end="", flush=True)
    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        while True:
            char = sys.stdin.read(1)
            if char in ("\r", "\n"):
                print(ANSI_CLEAR_LINE, end="", flush=True)
                return "next"
            if char.lower() == "q":
                print(ANSI_CLEAR_LINE, end="", flush=True)
                return "quit"
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)


def parse_from_date(value: str, tz_name: str) -> int:
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


def format_gap(previous_timestamp_ms: int, current_timestamp_ms: int) -> str:
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
    reactions = message.get("reactions") or []
    if not reactions:
        return ""

    rendered = []
    for reaction in reactions:
        emoji = repair_text(reaction.get("reaction", ""))
        actor = repair_text(reaction.get("actor", "unknown"))
        rendered.append(f"{actor}: {emoji}")
    return "Reactions: " + ", ".join(rendered)


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


def render_message(
    message: dict,
    tz_name: str,
    name_colors: dict[str, str],
    search_terms: list[str] | None = None,
    ansi_highlight: bool = False,
) -> list[str]:
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


def load_exports(input_path: str | None) -> tuple[list[dict], list[str], list[str]]:
    all_messages: list[dict] = []
    participants: set[str] = set()
    source_labels: list[str] = []

    if input_path:
        selected_path = Path(input_path)
        if selected_path.is_dir():
            json_paths, zip_paths, target_signatures = discover_folder_sources(selected_path)
            for path in json_paths:
                messages, signature = load_json_thread(path)
                all_messages.extend(messages)
                participants.update(signature)
                source_labels.append(str(path))

            for path in zip_paths:
                matched_threads, matched_signatures = load_zip_thread_members(path, target_signatures)
                for member_name, messages in matched_threads:
                    all_messages.extend(messages)
                    participants.update(
                        name for signature in matched_signatures for name in signature
                    )
                    source_labels.append(f"{path}!{member_name}")
        elif selected_path.suffix.lower() == ".zip":
            matched_threads, matched_signatures = load_zip_thread_members(selected_path, set())
            for member_name, messages in matched_threads:
                all_messages.extend(messages)
                participants.update(
                    name for signature in matched_signatures for name in signature
                )
                source_labels.append(f"{selected_path}!{member_name}")
        else:
            messages, signature = load_json_thread(selected_path)
            all_messages.extend(messages)
            participants.update(signature)
            source_labels.append(str(selected_path))
    else:
        json_paths = sorted(Path.cwd().glob("message_*.json"))
        for path in json_paths:
            messages, signature = load_json_thread(path)
            all_messages.extend(messages)
            participants.update(signature)
            source_labels.append(str(path))

    if not source_labels:
        raise FileNotFoundError("No Messenger message JSON files or Messenger export ZIPs found.")

    deduped: dict[tuple, dict] = {}
    for message in all_messages:
        deduped[message_dedupe_key(message)] = message

    messages = sorted(deduped.values(), key=message_sort_key)
    return messages, sorted(participants), source_labels


def filter_messages_from(messages: list[dict], from_timestamp_ms: int | None) -> list[dict]:
    if from_timestamp_ms is None:
        return messages
    return [message for message in messages if message["timestamp_ms"] >= from_timestamp_ms]


def filter_messages_until(messages: list[dict], until_timestamp_ms: int | None) -> list[dict]:
    if until_timestamp_ms is None:
        return messages
    return [message for message in messages if message["timestamp_ms"] <= until_timestamp_ms]


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


def run_pager(
    messages: list[dict],
    participants: list[str],
    tz_name: str,
    gap_seconds: int,
    use_color: bool,
    search_terms: list[str] | None = None,
    ansi_highlight: bool = False,
) -> None:
    name_colors = build_name_colors(participants, use_color)
    if participants:
        colored_participants = [name_colors.get(name, name) for name in participants]
        print("Chat: " + " / ".join(colored_participants))
        print()

    total = len(messages)
    previous_timestamp_ms: int | None = None
    for index, message in enumerate(messages, start=1):
        current_timestamp_ms = message["timestamp_ms"]
        if (
            previous_timestamp_ms is not None
            and current_timestamp_ms - previous_timestamp_ms >= gap_seconds * 1000
        ):
            print(format_gap(previous_timestamp_ms, current_timestamp_ms))
            print()
        print(
            "\n".join(
                render_message(
                    message,
                    tz_name,
                    name_colors,
                    search_terms=search_terms,
                    ansi_highlight=ansi_highlight,
                )
            )
        )
        print()
        previous_timestamp_ms = current_timestamp_ms
        if index >= total:
            print(f"End of chat. Displayed {total} messages.")
            return

        prompt = f"[{index}/{total}] Press Enter for the next message, or type q to quit: "
        action = read_pager_action(prompt)
        if action == "quit":
            print("Exiting.")
            return


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Display a Facebook Messenger export as a readable chat history."
    )
    parser.add_argument(
        "input_json",
        nargs="?",
        help="Optional path to a Messenger JSON file, Messenger ZIP export, or directory containing either.",
    )
    parser.add_argument(
        "-o",
        "--output",
        help="Write the result to a text file instead of stdout.",
    )
    parser.add_argument(
        "--timezone",
        default="Europe/Stockholm",
        help="Timezone for display, default: Europe/Stockholm.",
    )
    parser.add_argument(
        "--info",
        action="store_true",
        help="Show only stats instead of the full chat history.",
    )
    parser.add_argument(
        "--pager",
        action="store_true",
        help="Interactive mode: press Enter for the next message.",
    )
    parser.add_argument(
        "--gap-hours",
        type=float,
        default=DEFAULT_GAP_SECONDS / 3600,
        help="Show a gap marker when the pause between messages is at least this many hours.",
    )
    parser.add_argument(
        "--from",
        dest="from_date",
        help="Only include messages from this date and later (YYYY, YYYY-MM, or YYYY-MM-DD).",
    )
    parser.add_argument(
        "--until",
        dest="until_date",
        help="Only include messages up to this date (YYYY, YYYY-MM, or YYYY-MM-DD).",
    )
    parser.add_argument(
        "--search",
        nargs="+",
        help="Case-insensitive search terms. By default all terms must match.",
    )
    parser.add_argument(
        "--any",
        action="store_true",
        help="Match if any search term is found instead of requiring all terms.",
    )
    parser.add_argument(
        "--no-ansi",
        action="store_true",
        help="Disable ANSI highlight output in search results.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    messages, participants, paths = load_exports(args.input_json)
    from_timestamp_ms = None
    until_timestamp_ms = None
    ansi_enabled = sys.stdout.isatty() and not args.no_ansi
    use_color = ansi_enabled
    search_terms = [term.lower() for term in (args.search or []) if term.strip()]
    if args.from_date:
        from_timestamp_ms = parse_from_date(args.from_date, args.timezone)
        messages = filter_messages_from(messages, from_timestamp_ms)
    if args.until_date:
        until_timestamp_ms = parse_until_date(args.until_date, args.timezone)
        messages = filter_messages_until(messages, until_timestamp_ms)
    if search_terms:
        messages = filter_messages_search(messages, search_terms, args.timezone, args.any)

    if args.info:
        rendered = build_info_output(messages, participants, paths, args.timezone)
    elif args.pager:
        if args.output:
            raise SystemExit("--pager cannot be combined with --output.")
        if not sys.stdin.isatty():
            raise SystemExit("--pager requires an interactive terminal.")
        run_pager(
            messages,
            participants,
            args.timezone,
            int(args.gap_hours * 3600),
            use_color,
            search_terms=search_terms,
            ansi_highlight=ansi_enabled,
        )
        return
    else:
        rendered = build_output(
            messages,
            participants,
            args.timezone,
            int(args.gap_hours * 3600),
            use_color,
            search_terms=search_terms,
            ansi_highlight=ansi_enabled,
        )

    if args.output:
        Path(args.output).write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")


if __name__ == "__main__":
    main()
