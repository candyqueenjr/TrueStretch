"""Screenshots of every screen at several window sizes and in both themes (real fonts, invisible window).

    SHOT_SIZES   1440x900,1100x760,900x620          window sizes
    SHOT_THEMES  dark                                dark, light or dark,light
    SHOT_PAGES   see ALL_PAGES                       pages, tabs and dialogs to capture
    SHOT_OUT     tests/out                           where the PNGs go

Pages: game:valorant (+ :accounts / :display / :launch), optimize, matches (example data), matches:empty, mypc,
settings (+ :backups / :about). Dialogs: welcome:0 … welcome:4, update, troubleshoot, confirm, report.
Never run while VALORANT is running (it constructs an Engine)."""
import os, sys, tempfile, time
from datetime import datetime, timedelta
from pathlib import Path
os.environ["APPDATA"] = tempfile.mkdtemp(prefix="ts-shots-")
SCALE = float(os.environ.get("SHOT_SCALE", "1"))
if SCALE != 1:
    os.environ["QT_SCALE_FACTOR"] = str(SCALE)
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))
from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
from PySide6.QtWidgets import QApplication, QDialog
app = QApplication([])
from truestretch import display, updater
from truestretch.settings import Settings
from truestretch.games import GAMES
from truestretch.engine import Engine
from truestretch.ui import theme
from truestretch.ui.main_window import ConfirmResolutionDialog, MainWindow

OUT = Path(os.environ.get("SHOT_OUT", str(Path(__file__).resolve().parent / "out")))
OUT.mkdir(parents=True, exist_ok=True)
SIZES = [tuple(int(v) for v in s.split("x")) for s in os.environ.get("SHOT_SIZES", "1440x900,1100x760,900x620").split(",")]
THEMES = os.environ.get("SHOT_THEMES", "dark").split(",")
ALL_PAGES = ("game:valorant,game:valorant:servers,game:valorant:color,game:valorant:accounts,game:valorant:display,game:valorant:launch,"
             "optimize,matches,"
             "matches:empty,mypc,settings,settings:backups,settings:about,welcome:0,welcome:2,welcome:3,welcome:4,"
             "update,troubleshoot,confirm,report")
PAGES = os.environ.get("SHOT_PAGES", ALL_PAGES).split(",")
settings = Settings({g.id: g.default_settings() for g in GAMES})
settings.app["onboarded"] = True
settings.app["auto_update"] = False
theme.load_fonts(); theme.set_theme(THEMES[0])
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


def wait_for(cond, tries=400):
    for _ in range(tries):
        pump(0.05)
        if cond():
            return


def demo_matches():
    """Example history (nobody's real matches): 24 matches, Optimize Max applied after the 12th."""
    maps = ["Ascent", "Duality", "Triad", "Bonsai", "Jam", "Infinity", "Pitt", "Juliett"]
    demo, t0 = [], datetime(2026, 11, 10, 19, 0)
    for i in range(24):
        opt_on = i >= 12
        fps = (231 if opt_on else 204) + (i * 37 % 23) - 11
        demo.append({"started": (t0 + timedelta(hours=9 * i)).isoformat(timespec="seconds"),
                     "map": maps[i % len(maps)], "minutes": 26 + i * 7 % 13, "rounds": 20, "fps": float(fps),
                     "slow_share": 0.004 if opt_on else 0.011, "latency": 5.2 if opt_on else 6.1, "gpu_busy": 0.4,
                     "limit": "cpu", "hitches": 0, "stretch": "1440 × 1080", "optimized": opt_on})
    return demo


def demo_pings():
    """Example ping measurements (nobody's real connection): Europe, 9 game starts, Frankfurt preferred and lowest."""
    base = {"aws-euc1-prod.eu-gp-frankfurt-1": 24, "aws-euw3-prod.eu-gp-paris-1": 31, "aws-euw2-prod.eu-gp-london-1": 36,
            "aws-waw1-prod.eu-gp-warsaw-1": 38, "aws-eun1-prod.eu-gp-stockholm-1": 42, "aws-eus2-prod.eu-gp-madrid-1": 47,
            "aws-ist1-prod.eu-gp-istanbul-2": 61, "aws-ksa1-prod.eu-gp-riyadh-1": 98, "aws-aps1-prod.eu-gp-mumbai-1": 142,
            "aws-afs1-prod.eu-gp-capetown-1": 171, "aws-apne1-prod.eu-gp-tokyo-1": 251}
    demo, t0 = [], datetime(2026, 11, 12, 18, 30)
    for i in range(9):
        pods = {pod: ms + (i * 7 + len(pod)) % 5 - 2 for pod, ms in base.items()}
        demo.append({"when": (t0 + timedelta(hours=27 * i)).isoformat(timespec="seconds"), "pods": pods,
                     "preferred": ["aws-euc1-prod.eu-gp-frankfurt-1"]})
    return demo


def demo_status():
    return {"region": "eu", "name": "Europe", "entries": [], "older": [], "checked": datetime(2026, 11, 22, 20, 15)}


FAKE_RELEASE = updater.Release(
    version="9.9.9", tag="v9.9.9", url="https://example.invalid/release", download="", size=23_000_000, sha256="",
    notes="## TrueStretch 9.9.9 — Example\n\n**What's new**\n- An example entry for the screenshot.\n- Another one.\n\n"
          "**What's fixed**\n- A fix.\n\nAlready using TrueStretch? It updates itself.")


def make_dialog(key):
    kind, _, arg = key.partition(":")
    if kind == "welcome":
        from truestretch.ui.welcome import WelcomeDialog
        d = WelcomeDialog(e, win)
        d._go(int(arg or 0))
        if d.stack.currentIndex() == 1:           # the scan page: let the animation finish
            wait_for(lambda: not d.scan_timer.isActive(), 60)
        return d
    if kind == "update":
        from truestretch.ui.update import UpdateDialog
        return UpdateDialog(FAKE_RELEASE, win)
    if kind == "troubleshoot":
        from truestretch.ui.game_page import TroubleshootDialog
        return TroubleshootDialog(win, lambda: None)
    if kind == "confirm":
        return ConfirmResolutionDialog(win, display.Mode(1440, 1080, 144), 15, test=True)
    if kind == "report":
        page = win.pages["optimize"]
        if not page._scanned:
            win.navigate("optimize")
            wait_for(lambda: page._scanned and not page.busy)
        from PySide6.QtWidgets import QPlainTextEdit
        from truestretch.ui.widgets import button, hbox, label, vbox
        d = QDialog(win)
        d.setWindowTitle("TrueStretch — Technical report")
        d.resize(860, 620)
        report = QPlainTextEdit(page.opt.report())
        report.setReadOnly(True)
        report.setStyleSheet('font-family:"Cascadia Mono","Consolas"; font-size:9pt;')
        d.setLayout(vbox(label("Every value TrueStretch read, where it read it, and every change made this session. "
                               "Your Riot account ID is hidden.", "Muted", wrap=True), report,
                         hbox(button("Copy", "copy"), button("Save to Desktop", "download"), None,
                              button("Close"), spacing=8), spacing=12, margins=(20, 18, 20, 16)))
        return d
    return None


def split_page(page):
    """'game:valorant:accounts' -> ('game:valorant', 'accounts'); 'settings:backups' -> ('settings', 'backups')."""
    parts = page.split(":")
    if parts[0] == "game":
        return ":".join(parts[:2]), (parts[2] if len(parts) > 2 else "")
    return parts[0], (parts[1] if len(parts) > 1 else "")


def shoot_page(page, w, h, prefix):
    key, tab = split_page(page)
    win.navigate(key)
    if key == "optimize":
        opt_page = win.pages["optimize"]
        wait_for(lambda: opt_page._scanned and not opt_page.busy)
    elif key == "matches":
        mp = win.pages["matches"]
        wait_for(lambda: mp._loaded and not mp.busy, 200)
        mp.records = [] if tab == "empty" else demo_matches()
        mp.render()
    elif key.startswith("game:") and tab:
        win.pages[key].show_tab(tab)
        if tab == "servers":
            win.pages[key].servers.set_demo(demo_pings(), demo_status(), now=datetime(2026, 11, 22, 20, 0))
        if tab == "color":                      # shown switched on (settings only - the screen isn't touched)
            win.engine.gs("valorant").update(game_color=True, game_color_level="medium")
        win.pages[key].refresh()
    elif key == "settings" and tab:
        win.pages["settings"].show_tab(tab)
        win.pages["settings"].refresh()
    win.resize(w, h)
    pump(0.4)
    win.toast.hide()
    name = f"{prefix}{page.replace(':', '-')}-{w}x{h}.png"
    win.grab().save(str(OUT / name))
    print("saved", name)


def shoot_dialog(page, prefix):
    d = make_dialog(page)
    if d is None:
        return
    d.setWindowOpacity(0.0)
    d.show()
    pump(0.5)
    name = f"{prefix}{page.replace(':', '-')}.png"
    d.grab().save(str(OUT / name))
    print("saved", name)
    d.hide()
    d.deleteLater()
    pump(0.1)


DIALOGS = ("welcome", "update", "troubleshoot", "confirm", "report")
for theme_name in THEMES:
    prefix = f"{theme_name}-" if len(THEMES) > 1 else ""
    if theme.palette() is not theme.resolve(theme_name):
        settings.app["theme"] = theme_name
        win.apply_theme()
        pump(0.8)                                   # pages are rebuilt on a theme change
    for page in PAGES:
        if page.split(":")[0] in DIALOGS:
            win.resize(*SIZES[0])
            pump(0.2)
            shoot_dialog(page, prefix)
            continue
        for w, h in SIZES:
            shoot_page(page, w, h, prefix)
win.quit()
