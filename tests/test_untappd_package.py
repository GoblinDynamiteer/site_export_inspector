from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

import pytest

from export_inspector import untappd
from export_inspector.untappd import checkins, cli


FIXTURES = Path(__file__).parent / "fixtures"
UNTAPPD_JSON = FIXTURES / "untappd" / "checkins_multi.json"


def test_untappd_checkin_helpers_remain_import_compatible() -> None:
    assert untappd.load_export is checkins.load_export
    assert untappd.normalize_text is checkins.normalize_text
    assert untappd.parse_created_at is checkins.parse_created_at
    assert untappd.parse_rating is checkins.parse_rating
    assert untappd.display_rating is checkins.display_rating
    assert untappd.format_float is checkins.format_float
    assert untappd.DATE_FORMAT == checkins.DATE_FORMAT


def test_untappd_cli_names_remain_import_compatible() -> None:
    assert untappd.main is cli.main
    assert untappd.parse_args is cli.parse_args
    assert untappd.SearchResult is cli.SearchResult
    assert untappd.handle_info is cli.handle_info
    assert untappd.handle_search is cli.handle_search
    assert untappd.handle_show is cli.handle_show


def test_untappd_checkins_does_not_import_the_cli_or_qt() -> None:
    tree = ast.parse(Path(checkins.__file__).read_text(encoding="utf-8"))
    imported = {
        node.module if isinstance(node, ast.ImportFrom) else alias.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    assert not {name for name in imported if name and name.startswith(("PySide6", "export_inspector"))}


def test_untappd_package_import_does_not_load_the_cli() -> None:
    code = (
        "import sys\n"
        "from export_inspector import untappd\n"
        "import export_inspector.untappd.checkins\n"
        "assert 'export_inspector.untappd.cli' not in sys.modules\n"
        "untappd.normalize_text('x')\n"
        "assert 'export_inspector.untappd.cli' not in sys.modules\n"
    )
    subprocess.run([sys.executable, "-c", code], check=True)


def test_untappd_unknown_attribute_raises_attribute_error() -> None:
    with pytest.raises(AttributeError):
        untappd.no_such_name


@pytest.mark.parametrize("module", ["export_inspector.untappd", "export_inspector.untappd.cli"])
def test_untappd_runs_as_module(module: str) -> None:
    result = subprocess.run(
        [sys.executable, "-W", "error::RuntimeWarning", "-m", module, "show", str(UNTAPPD_JSON), "1"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.startswith("Beer: ")
    assert result.stderr == ""
