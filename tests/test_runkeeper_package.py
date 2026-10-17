from __future__ import annotations

import ast
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from export_inspector import runkeeper
from export_inspector.runkeeper import cli, formatting, loader, map, models, search


FIXTURES = Path(__file__).parent / "fixtures"
DOMAIN_MODULES = [models, formatting, loader, search, map]


def test_runkeeper_domain_names_remain_import_compatible() -> None:
    assert runkeeper.Activity is models.Activity
    assert runkeeper.load_export is loader.load_export
    assert runkeeper.load_route_points is loader.load_route_points
    assert runkeeper.format_dt is formatting.format_dt
    assert runkeeper.format_duration is formatting.format_duration
    assert runkeeper.sort_activities is search.sort_activities
    assert runkeeper.build_map_html is map.build_map_html
    assert runkeeper.color_for_activity is map.color_for_activity


def test_runkeeper_cli_names_remain_import_compatible() -> None:
    assert runkeeper.main is cli.main
    assert runkeeper.parse_args is cli.parse_args
    assert runkeeper.run_map is cli.run_map
    assert runkeeper.serve_directory is cli.serve_directory


@pytest.mark.parametrize("module", DOMAIN_MODULES, ids=lambda module: module.__name__)
def test_runkeeper_domain_modules_do_not_import_the_cli_or_qt(module) -> None:
    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    imported = {
        node.module if isinstance(node, ast.ImportFrom) else alias.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    assert not {name for name in imported if name and name.startswith("PySide6")}
    assert "export_inspector.runkeeper.cli" not in imported


def test_runkeeper_package_import_does_not_load_the_cli() -> None:
    code = (
        "import sys\n"
        "from export_inspector import runkeeper\n"
        "import export_inspector.runkeeper.loader\n"
        "runkeeper.format_duration(61)\n"
        "assert 'export_inspector.runkeeper.cli' not in sys.modules\n"
    )
    subprocess.run([sys.executable, "-c", code], check=True)


def test_runkeeper_unknown_attribute_raises_attribute_error() -> None:
    with pytest.raises(AttributeError):
        runkeeper.no_such_name


@pytest.mark.parametrize("module", ["export_inspector.runkeeper", "export_inspector.runkeeper.cli"])
def test_runkeeper_runs_as_module(module: str, tmp_path) -> None:
    zip_path = tmp_path / "runkeeper-export.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        for name in ("activity.gpx", "measurements.csv", "photos.csv"):
            archive.write(FIXTURES / "runkeeper" / name, name)
    result = subprocess.run(
        [sys.executable, "-W", "error::RuntimeWarning", "-m", module, "show", str(zip_path), "1"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.startswith("Index: 1\n")
    assert result.stderr == ""
