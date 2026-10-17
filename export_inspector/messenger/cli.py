"""The `messenger-chat` command: render, search and page through Messenger threads."""

from __future__ import annotations

import argparse
import sys
import termios
import tty
from pathlib import Path

from export_inspector.messenger.formatting import (
    DEFAULT_GAP_SECONDS,
    build_info_output,
    build_name_colors,
    build_output,
    format_gap,
    render_message,
)
from export_inspector.messenger.loader import load_exports
from export_inspector.messenger.search import (
    filter_messages_from,
    filter_messages_search,
    filter_messages_until,
    parse_from_date,
    parse_until_date,
)


ANSI_CLEAR_LINE = "\r\033[2K"


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
    """Entry point of the `messenger-chat` script."""
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
