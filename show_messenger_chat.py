#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import random
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


DEFAULT_GAP_SECONDS = 6 * 60 * 60
ANSI_RESET = "\033[0m"
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


def parse_from_date(value: str, tz_name: str) -> int:
    try:
        dt = datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=ZoneInfo(tz_name))
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"Invalid date '{value}'. Expected format: YYYY-MM-DD."
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


def render_message(message: dict, tz_name: str, name_colors: dict[str, str]) -> list[str]:
    sender = repair_text(message.get("sender_name", "Unknown"))
    timestamp_label = format_swedish_datetime(message["timestamp_ms"], tz_name)
    sender_label = name_colors.get(sender, sender)

    lines = [f"{timestamp_label}  {sender_label}"]

    content = repair_text(message.get("content", "")).strip()
    if content:
        lines.append(f"  {content}")

    for part in describe_attachment(message):
        lines.append(f"  {part}")

    reactions = describe_reactions(message)
    if reactions:
        lines.append(f"  {reactions}")

    return lines


def load_exports(input_path: str | None) -> tuple[list[dict], list[str], list[Path]]:
    if input_path:
        paths = [Path(input_path)]
    else:
        paths = sorted(Path.cwd().glob("message_*.json"))

    if not paths:
        raise FileNotFoundError("No message_*.json files found in the current directory.")

    all_messages: list[dict] = []
    participants: set[str] = set()
    for path in paths:
        data = json.loads(path.read_text(encoding="utf-8"))
        all_messages.extend(data.get("messages", []))
        for participant in data.get("participants", []):
            name = repair_text(participant.get("name", "")).strip()
            if name:
                participants.add(name)

    messages = sorted(all_messages, key=lambda item: item["timestamp_ms"])
    return messages, sorted(participants), paths


def filter_messages_from(messages: list[dict], from_timestamp_ms: int | None) -> list[dict]:
    if from_timestamp_ms is None:
        return messages
    return [message for message in messages if message["timestamp_ms"] >= from_timestamp_ms]


def build_output(
    messages: list[dict],
    participants: list[str],
    tz_name: str,
    gap_seconds: int,
    use_color: bool,
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
        message_lines = render_message(message, tz_name, name_colors)
        output_lines.extend(message_lines)
        output_lines.append("")
        previous_timestamp_ms = current_timestamp_ms

    return "\n".join(output_lines).rstrip() + "\n"


def build_info_output(
    messages: list[dict], participants: list[str], paths: list[Path], tz_name: str
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

    output_lines.append("JSON files: " + ", ".join(path.name for path in paths))
    return "\n".join(output_lines) + "\n"


def run_pager(
    messages: list[dict],
    participants: list[str],
    tz_name: str,
    gap_seconds: int,
    use_color: bool,
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
        print("\n".join(render_message(message, tz_name, name_colors)))
        print()
        previous_timestamp_ms = current_timestamp_ms
        if index >= total:
            print(f"End of chat. Displayed {total} messages.")
            return

        user_input = input(
            f"[{index}/{total}] Press Enter for the next message, or type q to quit: "
        )
        if user_input.strip().lower() in {"q", "quit", "exit"}:
            print("Exiting.")
            return


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Display a Facebook Messenger export as a readable chat history."
    )
    parser.add_argument(
        "input_json",
        nargs="?",
        help="Optional path to a specific Messenger JSON export.",
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
        help="Only include messages from this date and later (YYYY-MM-DD).",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    messages, participants, paths = load_exports(args.input_json)
    from_timestamp_ms = None
    use_color = sys.stdout.isatty()
    if args.from_date:
        from_timestamp_ms = parse_from_date(args.from_date, args.timezone)
        messages = filter_messages_from(messages, from_timestamp_ms)

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
        )
        return
    else:
        rendered = build_output(
            messages,
            participants,
            args.timezone,
            int(args.gap_hours * 3600),
            use_color,
        )

    if args.output:
        Path(args.output).write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")


if __name__ == "__main__":
    main()
