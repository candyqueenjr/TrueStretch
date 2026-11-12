"""Banner (README hero / social preview 1280x640) + logo PNGs in the tactical style."""
import sys
from pathlib import Path
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter
from PySide6.QtWidgets import QApplication
app = QApplication([])
from truestretch.ui import theme
from truestretch.ui.main_window import render_logo
theme.load_fonts()

A = Path(__file__).resolve().parents[1] / "docs" / "assets"
shot = QImage(str(A / "screens" / "app.png"))
NAVY, LINE, TEXT, MUTED, RED = "#0f1923", "#223140", "#ece8e1", "#8f9ba6", "#ff4655"


def cond(px, weight=QFont.Bold, spacing=2.0):
    f = QFont("Barlow Condensed")
    f.setPixelSize(px)
    f.setWeight(weight)
    f.setCapitalization(QFont.AllUppercase)
    f.setLetterSpacing(QFont.AbsoluteSpacing, spacing)
    return f


def brackets(p, r, size, color, t=3):
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(color))
    x0, y0, x1, y1 = r.left(), r.top(), r.right(), r.bottom()
    for x, y, dx, dy in ((x0, y0, 1, 1), (x1, y0, -1, 1), (x0, y1, 1, -1), (x1, y1, -1, -1)):
        p.drawRect(QRectF(x if dx > 0 else x - size, y if dy > 0 else y - t, size, t))
        p.drawRect(QRectF(x if dx > 0 else x - t, y if dy > 0 else y - size, t, size))


def banner(w, h, path):
    img = QImage(w, h, QImage.Format_ARGB32)
    img.fill(QColor(NAVY))
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.SmoothPixmapTransform)
    p.setPen(QColor(LINE))
    for x in (int(w * 0.06) - 20, int(w * 0.52)):
        p.drawLine(x, 0, x, h)
    p.drawLine(0, int(h * 0.88), w, int(h * 0.88))
    sw = int(w * 0.5)
    sh = int(sw * shot.height() / shot.width())
    x, y = int(w * 0.56), int((h * 0.88 - sh) / 2)
    p.drawImage(QRectF(x, y, sw, sh), shot)
    p.setPen(QColor("#34495c")); p.setBrush(Qt.NoBrush); p.drawRect(QRectF(x, y, sw, sh))
    brackets(p, QRectF(x - 12, y - 12, sw + 24, sh + 24), 30, RED)
    left = w * 0.06
    p.drawPixmap(int(left), int(h * 0.13), render_logo(int(h * 0.12), dpr=2.0))
    p.setFont(cond(int(h * 0.034), QFont.DemiBold, 5)); p.setPen(QColor(RED))
    p.drawText(QRectF(left, h * 0.30, w * 0.45, h * 0.06), Qt.AlignLeft | Qt.AlignVCenter, "// VALORANT · true stretched")
    p.setFont(cond(int(h * 0.14), QFont.Bold, 2)); p.setPen(QColor(TEXT))
    p.drawText(QRectF(left, h * 0.36, w * 0.5, h * 0.17), Qt.AlignLeft | Qt.AlignVCenter, "TrueStretch")
    f = QFont("Barlow"); f.setPixelSize(int(h * 0.04)); p.setFont(f); p.setPen(QColor(MUTED))
    p.drawText(QRectF(left, h * 0.55, w * 0.44, h * 0.16), Qt.AlignLeft | Qt.TextWordWrap,
               "One click. Fully automatic on NVIDIA, AMD and Intel. Plus Optimize Max.")
    p.setFont(cond(int(h * 0.028), QFont.DemiBold, 3.5))
    cx = left
    for chip in ["Free", "Auto-updates", "Every PC"]:
        tw = p.fontMetrics().horizontalAdvance(chip) + 34
        p.setBrush(QColor(RED)); p.setPen(Qt.NoPen); p.drawRect(QRectF(cx, h * 0.916 + 4, 6, 6))
        p.setPen(QColor(TEXT)); p.drawText(QRectF(cx + 14, h * 0.89, tw, h * 0.08), Qt.AlignLeft | Qt.AlignVCenter, chip)
        cx += tw + 26
    p.end()
    img.save(str(path))
    print("saved", path.name)


banner(1280, 640, A / "banner.png")
render_logo(256, dpr=1.0).save(str(A / "logo.png"))
render_logo(64, dpr=1.0).save(str(A / "favicon.png"))
print("logos saved")
