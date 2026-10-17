"""Check-in photo decoding and the clickable preview label with its full-size overlay."""

from __future__ import annotations

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QPoint, Qt
from PySide6.QtGui import QImageReader, QPixmap
from PySide6.QtWidgets import QApplication, QLabel

def pixmap_from_image_data(data: bytes) -> QPixmap:
    """Decode image bytes with EXIF orientation applied; an empty pixmap if undecodable."""
    buffer = QBuffer()
    buffer.setData(QByteArray(data))
    buffer.open(QIODevice.OpenModeFlag.ReadOnly)
    reader = QImageReader(buffer)
    reader.setAutoTransform(True)
    image = reader.read()
    if image.isNull():
        pixmap = QPixmap()
        pixmap.loadFromData(data)
        return pixmap
    return QPixmap.fromImage(image)


class PhotoPreviewLabel(QLabel):
    """Label that shows a photo scaled to fit, and the full-size photo while the left
    button is held (an overlay kept within the screen under the cursor)."""

    def __init__(self) -> None:
        super().__init__("No photo")
        self.original_pixmap: QPixmap | None = None
        self.overlay: QLabel | None = None
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumSize(320, 260)
        self.setWordWrap(True)

    def set_photo(self, pixmap: QPixmap | None, empty_text: str = "No photo") -> None:
        """Show `pixmap`, or `empty_text` when it is None or null."""
        self.original_pixmap = pixmap
        if pixmap is None or pixmap.isNull():
            self.setText(empty_text)
            self.setPixmap(QPixmap())
            self.close_overlay()
            return
        self.setText("")
        self.update_scaled_pixmap()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.update_scaled_pixmap()

    def mousePressEvent(self, event) -> None:
        if (
            event.button() == Qt.LeftButton
            and self.original_pixmap is not None
            and not self.original_pixmap.isNull()
        ):
            self.show_overlay(event.globalPosition().toPoint())
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        self.close_overlay()
        super().mouseReleaseEvent(event)

    def update_scaled_pixmap(self) -> None:
        if self.original_pixmap is None or self.original_pixmap.isNull():
            return
        scaled = self.original_pixmap.scaled(
            self.size(),
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation,
        )
        self.setPixmap(scaled)

    def show_overlay(self, position: QPoint) -> None:
        self.close_overlay()
        if self.original_pixmap is None:
            return
        screen = QApplication.screenAt(position) or self.screen()
        available = screen.availableGeometry() if screen else None
        pixmap = self.original_pixmap
        if available is not None:
            max_size = available.size() * 0.95
            if pixmap.width() > max_size.width() or pixmap.height() > max_size.height():
                pixmap = pixmap.scaled(
                    max_size,
                    Qt.KeepAspectRatio,
                    Qt.SmoothTransformation,
                )

        overlay = QLabel()
        overlay.setWindowFlags(
            Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
        )
        overlay.setAttribute(Qt.WA_DeleteOnClose)
        overlay.setPixmap(pixmap)
        overlay.adjustSize()
        overlay_position = position + QPoint(12, 12)
        if available is not None:
            overlay_position.setX(
                min(
                    max(overlay_position.x(), available.left()),
                    available.right() - overlay.width() + 1,
                )
            )
            overlay_position.setY(
                min(
                    max(overlay_position.y(), available.top()),
                    available.bottom() - overlay.height() + 1,
                )
            )
        overlay.move(overlay_position)
        overlay.mouseReleaseEvent = lambda event: overlay.close()
        overlay.show()
        self.overlay = overlay

    def close_overlay(self) -> None:
        if self.overlay is not None:
            self.overlay.close()
            self.overlay = None
