"""2x-resolution screenshots + focused crops for the website and README.
SITE_ONLY=color,servers writes only those files (the others are still rendered, not saved)."""
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
    only = [n for n in os.environ.get("SITE_ONLY", "").split(",") if n]
    if only and name.rsplit(".", 1)[0] not in only:
        return
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
win.navigate("matches")
mp = win.pages["matches"]
for _ in range(200):
    pump(0.05)
    if mp._loaded and not mp.busy:
        break
# Example history for the website (not anyone's real matches): 24 matches, Optimize Max applied after the 12th.
from datetime import datetime, timedelta
maps = ["Ascent", "Duality", "Triad", "Bonsai", "Jam", "Infinity", "Pitt", "Juliett"]
demo, t0 = [], datetime(2026, 11, 10, 19, 0)
for i in range(24):
    opt_on = i >= 12
    fps = (231 if opt_on else 204) + (i * 37 % 23) - 11
    demo.append({"started": (t0 + timedelta(hours=9 * i)).isoformat(timespec="seconds"), "map": maps[i % len(maps)],
                 "minutes": 26 + i * 7 % 13, "rounds": 20, "fps": float(fps), "slow_share": 0.004 if opt_on else 0.011,
                 "latency": 5.2 if opt_on else 6.1, "gpu_busy": 0.4, "limit": "cpu", "hitches": 0,
                 "stretch": "1440 × 1080", "optimized": opt_on})
mp.records = demo
mp.render()
save(win, "matches.png")
# Example ping measurements for the website (nobody's real connection): Europe, 9 game starts, Frankfurt preferred.
base = {"aws-euc1-prod.eu-gp-frankfurt-1": 24, "aws-euw3-prod.eu-gp-paris-1": 31, "aws-euw2-prod.eu-gp-london-1": 36,
        "aws-waw1-prod.eu-gp-warsaw-1": 38, "aws-eun1-prod.eu-gp-stockholm-1": 42, "aws-eus2-prod.eu-gp-madrid-1": 47,
        "aws-ist1-prod.eu-gp-istanbul-2": 61, "aws-ksa1-prod.eu-gp-riyadh-1": 98, "aws-aps1-prod.eu-gp-mumbai-1": 142,
        "aws-afs1-prod.eu-gp-capetown-1": 171, "aws-apne1-prod.eu-gp-tokyo-1": 251}
pings, t0 = [], datetime(2026, 11, 12, 18, 30)
for i in range(9):
    pings.append({"when": (t0 + timedelta(hours=27 * i)).isoformat(timespec="seconds"),
                  "pods": {pod: ms + (i * 7 + len(pod)) % 5 - 2 for pod, ms in base.items()},
                  "preferred": ["aws-euc1-prod.eu-gp-frankfurt-1"]})
win.navigate("game:valorant")
game.show_tab("servers")
pump()
game.servers.set_demo(pings, {"region": "eu", "name": "Europe", "entries": [], "older": [],
                              "checked": datetime(2026, 11, 22, 20, 15)}, now=datetime(2026, 11, 22, 20, 0))
game.refresh(); game.settle()
pump(0.6)
save(card_of(game.servers.board), "servers.png")
# Game Color with an example NVIDIA screen (the website must not depend on the PC that renders it).
from truestretch.gamecolor import Screen                       # noqa: E402
gs.update(game_color=True, game_color_level="medium")
e.color_screen = lambda gid="valorant": (Screen("nvidia", "demo", "demo", 50, 50, 0, 100), None)
game.show_tab("color")
game.color.screen = None
game.refresh(); game.settle()
pump(0.6)
save(card_of(game.color.preview), "color.png")
win.navigate("mypc")
pump(0.8)
save(win, "mypc.png")
win.quit()
