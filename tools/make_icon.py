"""Renders assets/logo.svg into a multi-size Windows icon (assets/app.ico)."""

import io
import sys
from pathlib import Path

from PIL import Image
from PySide6.QtCore import QBuffer, QIODevice, QRectF, Qt
from PySide6.QtGui import QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

ROOT = Path(__file__).resolve().parent.parent
SIZES = [16, 20, 24, 32, 40, 48, 64, 128, 256]


def render(renderer, size):
    image = QImage(size, size, QImage.Format_ARGB32)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing)
    renderer.render(painter, QRectF(0, 0, size, size))
    painter.end()
    buffer = QBuffer()
    buffer.open(QIODevice.WriteOnly)
    image.save(buffer, "PNG")
    return Image.open(io.BytesIO(bytes(buffer.data()))).convert("RGBA")


def main():
    app = QGuiApplication(sys.argv)  # noqa: F841 - Qt needs an app for painting
    renderer = QSvgRenderer(str(ROOT / "assets" / "logo.svg"))
    images = [render(renderer, s) for s in SIZES]
    out = ROOT / "assets" / "app.ico"
    images[-1].save(out, format="ICO", sizes=[(s, s) for s in SIZES], append_images=images[:-1])
    images[-1].save(ROOT / "assets" / "app.png")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
