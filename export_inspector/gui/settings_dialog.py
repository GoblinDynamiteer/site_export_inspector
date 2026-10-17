"""The Settings dialog (File > Settings…)."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QFontMetrics, QPalette
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QSlider,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from export_inspector.gui.appearance import (
    DETAIL_POINT_SIZE_MAX,
    TEXT_SCALE_MAX,
    TEXT_SCALE_MIN,
    TEXT_SCALE_STEP,
    AppearanceSettings,
    apply_appearance,
    detail_font,
    interface_font,
    load_appearance,
    monospace_families,
    save_appearance,
)


class SettingsDialog(QDialog):
    """Settings window: a category list on the left and one page per category.

    Changes are previewed in the dialog and only saved and applied on Apply or OK.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Settings — Export Inspector")

        self.categories = QListWidget()
        self.pages = QStackedWidget()
        self.categories.currentRowChanged.connect(self.pages.setCurrentIndex)

        self.scale_slider = QSlider(Qt.Horizontal)
        self.scale_slider.setRange(TEXT_SCALE_MIN, TEXT_SCALE_MAX)
        self.scale_slider.setSingleStep(5)
        self.scale_slider.setPageStep(TEXT_SCALE_STEP)
        self.scale_value = QLabel()
        scale_row = QHBoxLayout()
        scale_row.addWidget(self.scale_slider, 1)
        scale_row.addWidget(self.scale_value)
        appearance_form = QFormLayout()
        appearance_form.addRow("Text size", scale_row)
        scale_hint = QLabel(
            "Relative to the system font. Shortcuts: Ctrl++ larger, Ctrl+- smaller, Ctrl+0 reset."
        )
        scale_hint.setWordWrap(True)
        self.add_page("Appearance", appearance_form, scale_hint)

        self.detail_family = QComboBox()
        self.detail_family.addItem("System monospace", "")
        for family in monospace_families():
            self.detail_family.addItem(family, family)
        self.detail_size = QSpinBox()
        self.detail_size.setRange(0, DETAIL_POINT_SIZE_MAX)
        self.detail_size.setSpecialValueText("Same as interface")
        self.detail_size.setSuffix(" pt")
        detail_form = QFormLayout()
        detail_form.addRow("Family", self.detail_family)
        detail_form.addRow("Size", self.detail_size)
        self.add_page("Detail panes", detail_form)

        self.preview_text = QLabel("Example Pale Ale · Sample Brewery · 3.75")
        self.preview_mono = QLabel("2026-10-10 18:42  check-in #128")
        preview = QFrame()
        preview.setFrameShape(QFrame.StyledPanel)
        preview.setAutoFillBackground(True)
        preview.setBackgroundRole(QPalette.Base)
        preview_layout = QVBoxLayout(preview)
        preview_layout.addWidget(self.preview_text)
        preview_layout.addWidget(self.preview_mono)
        preview_layout.addStretch(1)

        right = QVBoxLayout()
        right.addWidget(self.pages)
        right.addWidget(QLabel("Preview"))
        right.addWidget(preview, 1)
        body = QHBoxLayout()
        body.addWidget(self.categories)
        body.addLayout(right, 1)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.RestoreDefaults
            | QDialogButtonBox.Cancel
            | QDialogButtonBox.Apply
            | QDialogButtonBox.Ok
        )
        self.buttons.button(QDialogButtonBox.RestoreDefaults).clicked.connect(
            self.restore_defaults
        )
        self.buttons.button(QDialogButtonBox.Apply).clicked.connect(self.apply)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)

        root = QVBoxLayout(self)
        root.addLayout(body, 1)
        root.addWidget(self.buttons)

        self.set_controls(load_appearance())
        self.scale_slider.valueChanged.connect(self.update_preview)
        self.detail_family.currentIndexChanged.connect(self.update_preview)
        self.detail_size.valueChanged.connect(self.update_preview)
        self.update_preview()
        self.categories.setCurrentRow(0)
        self.categories.setFixedWidth(self.categories.sizeHintForColumn(0) + 32)
        metrics = QFontMetrics(self.font())
        self.resize(
            max(self.sizeHint().width(), metrics.horizontalAdvance("M") * 40),
            max(self.sizeHint().height(), metrics.height() * 18),
        )

    def add_page(self, title: str, *contents) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(12, 0, 0, 0)
        heading = QLabel(title)
        heading_font = QFont()
        heading_font.setBold(True)
        heading.setFont(heading_font)
        layout.addWidget(heading)
        for item in contents:
            if isinstance(item, QWidget):
                layout.addWidget(item)
            else:
                layout.addLayout(item)
        layout.addStretch(1)
        self.categories.addItem(title)
        self.pages.addWidget(page)

    def set_controls(self, appearance: AppearanceSettings) -> None:
        self.scale_slider.setValue(appearance.text_scale)
        index = self.detail_family.findData(appearance.detail_family)
        self.detail_family.setCurrentIndex(max(index, 0))
        self.detail_size.setValue(appearance.detail_point_size)

    def pending(self) -> AppearanceSettings:
        """Return the settings as currently chosen in the dialog."""
        return AppearanceSettings(
            text_scale=self.scale_slider.value(),
            detail_family=str(self.detail_family.currentData() or ""),
            detail_point_size=self.detail_size.value(),
        )

    def update_preview(self) -> None:
        appearance = self.pending()
        self.scale_value.setText(f"{appearance.text_scale} %")
        self.preview_text.setFont(interface_font(appearance))
        self.preview_mono.setFont(detail_font(appearance))

    def restore_defaults(self) -> None:
        self.set_controls(AppearanceSettings())

    def apply(self) -> None:
        appearance = self.pending()
        save_appearance(appearance)
        apply_appearance(appearance)
        self.update_preview()

    def accept(self) -> None:
        self.apply()
        super().accept()
