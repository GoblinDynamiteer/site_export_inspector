"""Text snapshots of GUI state for behaviour-preserving refactors.

A ``Snapshot`` collects named sections of visible GUI text (labels, table cells, detail
panes) and compares them with ``tests/golden/<name>.txt``. Run pytest with
``--update-golden`` to rewrite the golden files after an intended change, then review
the diff. Tests get snapshots from the ``make_snapshot`` fixture in ``conftest.py``.
"""

from __future__ import annotations

import difflib
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QTableView

GOLDEN_DIR = Path(__file__).parent / "golden"
FIXTURES = Path(__file__).parent / "fixtures"


class Snapshot:
    def __init__(
        self, name: str, replacements: dict[str, str] | None = None, update: bool = False
    ) -> None:
        self.name = name
        self.update = update
        self.sections: list[str] = []
        self.replacements = {str(FIXTURES): "<FIXTURES>", **(replacements or {})}

    def add(self, title: str, text: str) -> None:
        for old, new in self.replacements.items():
            text = text.replace(old, new)
        self.sections.append(f"== {title}\n{text.rstrip()}\n")

    def add_table(self, title: str, view: QTableView) -> None:
        self.add(title, "\n".join(" | ".join(row) for row in table_rows(view)))

    def text(self) -> str:
        return "\n".join(self.sections)

    def assert_matches(self) -> None:
        path = GOLDEN_DIR / f"{self.name}.txt"
        actual = self.text()
        if self.update:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(actual, encoding="utf-8")
            return
        assert path.exists(), f"Missing golden file {path}; run pytest with --update-golden"
        expected = path.read_text(encoding="utf-8")
        if actual != expected:
            diff = "".join(
                difflib.unified_diff(
                    expected.splitlines(keepends=True),
                    actual.splitlines(keepends=True),
                    fromfile=f"golden/{self.name}.txt",
                    tofile="actual",
                )
            )
            raise AssertionError(f"GUI snapshot changed:\n{diff}")


def table_rows(view: QTableView) -> list[list[str]]:
    """Return the header and all visible cells of a table view as text."""
    model = view.model()
    columns = range(model.columnCount())
    rows = [[str(model.headerData(c, Qt.Horizontal) or "") for c in columns]]
    for row in range(model.rowCount()):
        rows.append([str(model.index(row, c).data() or "") for c in columns])
    return rows


def each_row_detail(view: QTableView, detail) -> list[str]:
    """Select every row in turn and return the detail pane text for each."""
    texts = []
    for row in range(view.model().rowCount()):
        view.selectRow(row)
        QApplication.processEvents()
        texts.append(detail.toPlainText())
    return texts
