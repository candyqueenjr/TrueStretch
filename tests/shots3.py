"""Screenshots of every main page at several window sizes (real fonts, invisible window)."""
import os, sys, tempfile, time
from pathlib import Path
os.environ["APPDATA"] = tempfile.mkdtemp(prefix="ts-shots-")
SCALE = float(os.environ.get("SHOT_SCALE", "1"))
if SCALE != 1:
    os.environ["QT_SCALE_FACTOR"] = str(SCALE)
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

OUT = Path(os.environ.get("SHOT_OUT", str(Path(__file__).resolve().parent / "out")))
OUT.mkdir(parents=True, exist_ok=True)
SIZES = [tuple(int(v) for v in s.split("x")) for s in os.environ.get("SHOT_SIZES", "1440x900,1100x760,900x620").split(",")]
PAGES = os.environ.get("SHOT_PAGES", "game:valorant,optimize,mypc,settings").split(",")
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
win.show()
win.apply_theme()


def pump(seconds=0.3):
    end = time.time() + seconds
    while time.time() < end:
        app.processEvents()
        time.sleep(0.02)


for page in PAGES:
    win.navigate(page)
    if page == "optimize":
        opt_page = win.pages["optimize"]
        for _ in range(400):
            pump(0.05)
            if opt_page._scanned and not opt_page.busy:
                break
    for w, h in SIZES:
        win.resize(w, h)
        pump(0.4)
        win.toast.hide()
        name = f"{page.replace(':', '-')}-{w}x{h}.png"
        win.grab().save(str(OUT / name))
        print("saved", name)
win.quit()
