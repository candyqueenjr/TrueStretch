"""2x-resolution screenshots + focused crops for the website and README."""
import os, sys, tempfile, time
from pathlib import Path
os.environ["APPDATA"] = tempfile.mkdtemp(prefix="ts-site-")
os.environ["QT_SCALE_FACTOR"] = "2"
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["QT_QPA_FONTDIR"] = "C:/Windows/Fonts"
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))
from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
from PySide6.QtWidgets import QApplication
app = QApplication([])
from truestretch.settings import Settings
from truestretch.games import GAMES
from truestretch.engine import Engine
from truestretch.ui import theme
from truestretch.ui.main_window import MainWindow
from truestretch.ui.widgets import Card

OUT = Path(__file__).resolve().parents[1] / "docs" / "assets" / "screens"
OUT.mkdir(parents=True, exist_ok=True)
settings = Settings({g.id: g.default_settings() for g in GAMES})
settings.app["onboarded"] = True
settings.app["auto_update"] = False
theme.load_fonts(); theme.set_theme("dark")
app.setStyleSheet(theme.stylesheet())
e = Engine(settings); e.timer.stop()
gs = e.gs("valorant")
gs["width"], gs["height"] = 1440, 1080
gs["nicknames"] = {t.key: ("Main account" if i == 0 else f"Account {i + 1}") for i, t in enumerate(e.targets("valorant"))}
win = MainWindow(e)
win.setWindowOpacity(0.0)
win.resize(1360, 860)
win.show()
win.apply_theme()


def pump(seconds=0.4):
    end = time.time() + seconds
    while time.time() < end:
        app.processEvents()
        time.sleep(0.02)


def card_of(widget):
    while widget is not None and not isinstance(widget, Card):
        widget = widget.parentWidget()
    return widget


def save(widget, name):
    """Whole window, or a crop of one panel taken from the window render (so the real background is included)."""
    from PySide6.QtCore import QPoint, QRect
    pump(0.3)
    win.toast.hide()
    if widget is win:
        img = win.grab()
    else:
        scroller = widget.parentWidget()
        while scroller is not None and not hasattr(scroller, "ensureWidgetVisible"):
            scroller = scroller.parentWidget()
        if scroller is not None:
            y = widget.mapTo(scroller.widget(), QPoint(0, 0)).y()
            scroller.verticalScrollBar().setValue(max(0, y - 16))
            pump(0.3)
        top_left = widget.mapTo(win, QPoint(0, 0))
        stack_top = win.stack.mapTo(win, QPoint(0, 0)).y()
        y0 = max(top_left.y() - 12, stack_top)
        bottom = min(top_left.y() + widget.height() + 12, stack_top + win.stack.height())
        img = win.grab(QRect(top_left.x() - 12, y0, widget.width() + 24, bottom - y0))
    img.save(str(OUT / name))
    print("saved", name, img.width(), "x", img.height())


win.navigate("game:valorant")
pump()
save(win, "app.png")
game = win.pages["game:valorant"]
save(card_of(game.tiles[0][0]), "stretch.png")
win.navigate("optimize")
page = win.pages["optimize"]
for _ in range(400):
    pump(0.05)
    if page._scanned and not page.busy:
        break
pump()
save(card_of(page.score), "optimize-score.png")
first_group = page.list.itemAt(0).widget()
save(first_group, "optimize.png")
save(win, "optimize-full.png")
page.tabs.setCurrentIndex(1)
pump()
save(win, "diagnostics.png")
win.navigate("mypc")
pump(0.8)
save(win, "mypc.png")
win.quit()
