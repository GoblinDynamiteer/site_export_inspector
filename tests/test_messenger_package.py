from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

import pytest

from export_inspector import messenger, messenger_chat
from export_inspector.messenger import cli, formatting, loader, search


FIXTURES = Path(__file__).parent / "fixtures"
MESSENGER_JSON = FIXTURES / "messenger" / "message_1.json"
DOMAIN_MODULES = [loader, formatting, search]


@pytest.mark.parametrize("module", [messenger_chat, messenger], ids=["messenger_chat", "messenger"])
def test_messenger_names_remain_import_compatible(module) -> None:
    assert module.load_exports is loader.load_exports
    assert module.discover_threads is loader.discover_threads
    assert module.load_json_thread is loader.load_json_thread
    assert module.repair_text is formatting.repair_text
    assert module.render_message is formatting.render_message
    assert module.format_gap is formatting.format_gap
    assert module.DEFAULT_GAP_SECONDS == formatting.DEFAULT_GAP_SECONDS
    assert module.filter_messages_from is search.filter_messages_from
    assert module.parse_from_date is search.parse_from_date
    assert module.main is cli.main
    assert module.run_pager is cli.run_pager


@pytest.mark.parametrize("module", DOMAIN_MODULES, ids=lambda module: module.__name__)
def test_messenger_domain_modules_do_not_import_the_cli_or_qt(module) -> None:
    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    imported = {
        node.module if isinstance(node, ast.ImportFrom) else alias.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    assert not {name for name in imported if name and name.startswith("PySide6")}
    assert not imported & {"export_inspector.messenger.cli", "termios", "tty"}


def test_messenger_imports_do_not_load_the_cli() -> None:
    code = (
        "import sys\n"
        "from export_inspector import messenger, messenger_chat\n"
        "import export_inspector.messenger.search\n"
        "messenger_chat.repair_text('x')\n"
        "assert 'export_inspector.messenger.cli' not in sys.modules\n"
    )
    subprocess.run([sys.executable, "-c", code], check=True)


@pytest.mark.parametrize("module", [messenger, messenger_chat], ids=["messenger", "messenger_chat"])
def test_messenger_unknown_attribute_raises_attribute_error(module) -> None:
    with pytest.raises(AttributeError):
        module.no_such_name


@pytest.mark.parametrize(
    "command",
    [
        ["-m", "export_inspector.messenger"],
        ["-m", "export_inspector.messenger.cli"],
        ["-m", "export_inspector.messenger_chat"],
    ],
    ids=["package", "cli", "wrapper"],
)
def test_messenger_runs_as_module(command: list[str]) -> None:
    result = subprocess.run(
        [sys.executable, "-W", "error::RuntimeWarning", *command, str(MESSENGER_JSON), "--info"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.startswith("Files: 1\nMessages: 2\n")
    assert result.stderr == ""


def test_messenger_chat_script_runs_without_installed_package() -> None:
    script_path = Path(messenger_chat.__file__).resolve()
    result = subprocess.run(
        [sys.executable, "-S", str(script_path), "--help"],
        capture_output=True,
        text=True,
        check=True,
        cwd=script_path.parent,
    )
    assert result.stdout.startswith("usage: messenger_chat.py")


MESSAGES = [
    {"sender_name": "Alice Example", "timestamp_ms": 1641031200000, "content": "Sample trail plan"},
    {
        "sender_name": "Bob Example",
        "timestamp_ms": 1641034800000,
        "content": "Confirmed",
        "reactions": [{"reaction": "+1", "actor": "Alice Example"}],
    },
    {"timestamp_ms": 1641300000000, "photos": [{"uri": "photos/a.jpg"}]},
]


def test_message_search_blob_is_lowercased_and_includes_attachments() -> None:
    assert search.message_search_blob(MESSAGES[1], "UTC").split("\n") == [
        "bob example",
        "confirmed",
        "2022-01-01 11:00:00",
        "reactions: alice example: +1",
    ]
    assert search.message_search_blob(MESSAGES[2], "UTC").split("\n") == [
        "",
        "",
        "2022-01-04 12:40:00",
        "[sent photo: 1]",
        "[photo ref] photos/a.jpg",
    ]


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("", [0, 1, 2]),
        ("   ", [0, 1, 2]),
        ("TRAIL", [0]),
        ("alice", [0, 1]),
        ("alice confirmed", [1]),
        ("photo ref", [2]),
        ("2022-01-01", [0, 1]),
        ("nomatch", []),
    ],
)
def test_filter_messages_text_matches_every_term(query: str, expected: list[int]) -> None:
    result = search.filter_messages_text(MESSAGES, query, "UTC")
    assert result == [MESSAGES[index] for index in expected]


def test_filter_messages_text_uses_the_timezone() -> None:
    assert search.filter_messages_text(MESSAGES, "2022-01-01 11:00", "UTC") == [MESSAGES[1]]
    assert search.filter_messages_text(MESSAGES, "2022-01-01 12:00", "Europe/Stockholm") == [
        MESSAGES[1]
    ]
