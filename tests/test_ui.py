"""UI layout rules (2.0.1), checked on the real window drawn offscreen: failing checks read as problems, the
Get VALORANT button appears only when the game is missing, the top navigation keeps readable labels at every
window width, the Settings tab bar is centred over its pages, the Optimize score card stays compact on a narrow
window, the Matches stat cards line up, and the My PC page survives a failing display read without going blank.
Needs VALORANT closed (it builds an Engine); nothing on the PC is changed."""
import logging
import os
import sys
import tempfile
import time
from pathlib import Path

os.environ["APPDATA"] = tempfile.mkdtemp(prefix="ts-ui-")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", "C:/Windows/Fonts")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtWidgets import QApplication                 # noqa: E402

app = QApplication([])
logging.getLogger().addHandler(logging.NullHandler())      # the deliberate failure below is logged, not printed

from truestretch import displayconfig                       # noqa: E402
from truestretch.engine import Check, Engine                # noqa: E402
from truestretch.games import GAMES                         # noqa: E402
from truestretch.settings import Settings                   # noqa: E402
from truestretch.ui import theme                            # noqa: E402
from truestretch.ui.main_window import MainWindow           # noqa: E402

fails = []


def check(c, t):
    print(("PASS " if c else "FAIL ") + t)
    c or fails.append(t)


def pump(seconds=0.25):
    end = time.time() + seconds
    while time.time() < end:
        app.processEvents()
        time.sleep(0.01)


# ---- Check wording -----------------------------------------------------------
ok = Check("installed", "VALORANT installed", True, "", problem="VALORANT not found")
bad = Check("installed", "VALORANT installed", False, "", problem="VALORANT not found")
warn = Check("monitors", "Monitor drivers off", None, "", problem="Monitor drivers still on")
plain = Check("x", "Something", False, "")
check(ok.headline == "VALORANT installed", "a passing check keeps its title")
check(bad.headline == "VALORANT not found", "a failing check reads as the problem")
check(warn.headline == "Monitor drivers still on", "a warning check reads as the problem too")
check(plain.headline == "Something", "a check without problem wording falls back to its title")

# ---- the real window ----------------------------------------------------------
settings = Settings({g.id: g.default_settings() for g in GAMES})
settings.app["onboarded"] = True
settings.app["auto_update"] = False
theme.load_fonts()
theme.set_theme("dark")
app.setStyleSheet(theme.stylesheet())
engine = Engine(settings)
engine.timer.stop()
win = MainWindow(engine)
win.show()
pump()
game = win.pages["game:valorant"]
installed = engine.info["valorant"].installed
checks = engine.checks("valorant")
check(all(c.problem for c in checks), "every game-page check has problem wording")
check(all(c.headline != c.title for c in checks if c.ok is not True),
      "failing checks never show their success title")
check(game.btn_get.isVisible() == (not installed), "Get VALORANT is shown exactly when the game is missing")
if not installed:
    check("not found" in game.checks_line.text().lower(), "the one-line summary names the missing game")
    check("version" not in game.subtitle.text(), "no version is claimed for a game that isn't installed")


def nav_fits():
    return all(b.width() >= b.sizeHint().width() and b.text() == b.property("full_text")
               for b in win.nav_buttons.values())


for w, h in ((1280, 800), (900, 620), (1100, 760), (1280, 800)):
    win.resize(w, h)
    pump(0.3)
    check(win.width() == w, f"the window really is {w} px wide (no layout forcing it wider)")
    check(nav_fits(), f"all five navigation labels are shown unclipped at {w} px")

# Settings tab bar centred over the pages (it used to hug the left edge).
win.navigate("settings")
win.resize(1280, 800)
pump(0.3)
shell = win.pages["settings"]
bar = shell.tabs
centre = bar.mapTo(win, bar.rect().center()).x()
check(abs(centre - win.width() / 2) < 40, f"Settings tabs are centred (centre at {centre} of {win.width()})")
shell.show_tab("about")
pump(0.1)
check(shell.stack.currentWidget() is shell.about, "show_tab switches the page under the tab bar")
shell.show_tab("general")

# Optimize score card compact at 900 px: score and counts side by side, buttons below.
win.navigate("optimize")
page = win.pages["optimize"]
for _ in range(600):
    pump(0.05)
    if page._scanned and not page.busy:
        break
summary = page.score
while summary is not None and summary.objectName() != "Card":
    summary = summary.parentWidget()
win.resize(900, 620)
pump(0.4)
check(summary is not None and summary.height() <= 260,
      f"Optimize score card is {summary.height() if summary else '?'} px tall at 900 px (was 320)")
score_y = page.score.mapTo(win, page.score.rect().topLeft()).y()
count_y = page.stat_labels["improve"].mapTo(win, page.stat_labels["improve"].rect().topLeft()).y()
check(abs(score_y - count_y) < 40, "score and counts stay on one row at 900 px")
btn_y = page.btn_apply.mapTo(win, page.btn_apply.rect().topLeft()).y()
check(btn_y > score_y + 40, "the buttons drop below the numbers at 900 px")
win.resize(1280, 800)
pump(0.3)
btn_y = page.btn_apply.mapTo(win, page.btn_apply.rect().center()).y()
score_c = page.score.mapTo(win, page.score.rect().center()).y()
check(abs(btn_y - score_c) < 60, "at 1280 px the buttons sit beside the score again")

# Matches stat cards: captions on one line even when one card's subtitle wraps.
win.navigate("matches")
mp = win.pages["matches"]
for _ in range(200):
    pump(0.05)
    if mp._loaded and not mp.busy:
        break
mp.records = []
mp.render()
win.resize(900, 620)
pump(0.3)
tops = [c.body.itemAt(0).widget().mapTo(win, c.body.itemAt(0).widget().rect().topLeft()).y()
        for c in mp.cards.values()]
check(max(tops) - min(tops) <= 2, f"Matches captions line up at 900 px (tops {tops})")

# My PC: a failing display read leaves the page intact with a note, not an empty card.
win.resize(1280, 800)
win.navigate("mypc")
pump(0.5)
pc = win.pages["mypc"]
rows_before = pc.health_box.count()
check(rows_before > 0, f"My PC shows {rows_before} health group(s)")
screen_widgets = [pc.screens.body.itemAt(i).widget() for i in range(pc.screens.body.count())]
screen_widgets = [w for w in screen_widgets if w is not None]
check(len(screen_widgets) >= 2 and all(w.isVisible() for w in screen_widgets),
      f"the screen rows are visible right after opening the page ({len(screen_widgets)} widgets)")
check(pc.screens.height() > 120, f"the screens card has its real height right away ({pc.screens.height()} px)")
heights = [pc.health_box.itemAt(i).widget().height() for i in range(pc.health_box.count())]
check(len(set(heights)) > 1 or heights[0] < 400, f"health cards aren't all stretched to one size ({heights})")
real_monitors = displayconfig.monitors


def broken():
    raise OSError("display API unavailable (test)")


displayconfig.monitors = broken
try:
    pc.refresh()
    pump(0.3)
    texts = []
    for i in range(pc.screens.body.count()):
        item = pc.screens.body.itemAt(i)
        lay = item.layout()
        if lay is not None:
            for j in range(lay.count()):
                w = lay.itemAt(j).widget()
                if w is not None and hasattr(w, "text"):
                    texts.append(w.text())
    check(any("Couldn't read your screens" in t for t in texts), "a failing screens read shows a plain note")
    check(any("Your screens" in t for t in texts), "the screens card keeps its heading")
    check(pc.health_box.count() == rows_before, "the health groups are still there after the failure")
finally:
    displayconfig.monitors = real_monitors
pc.refresh()
pump(0.3)
check(pc.screens.body.count() > 2, "the screens come back on the next refresh")

# ---- Servers tab (2.1): the ping board ----------------------------------------------------------------------------
from datetime import datetime, timedelta                    # noqa: E402

win.resize(900, 620)
pump(0.3)
win.navigate("game:valorant")
game.show_tab("servers")
pump(0.3)
check(game.tabs.tabText(game.tabs.currentIndex()) == "Servers", "the VALORANT page has a Servers tab")
servers = game.servers
check(servers.isVisible() and servers.board.isVisible(), "the Servers tab shows the ping board")
demo = []
base = {"aws-euc1-prod.eu-gp-frankfurt-1": 24, "aws-euw3-prod.eu-gp-paris-1": 31, "aws-ksa1-prod.eu-gp-riyadh-1": 98,
        "aws-apne1-prod.eu-gp-tokyo-1": 251}
t0 = datetime(2026, 11, 12, 18, 30)
for i in range(5):
    demo.append({"when": (t0 + timedelta(days=i)).isoformat(timespec="seconds"),
                 "pods": {pod: ms + i % 3 for pod, ms in base.items()}, "preferred": ["aws-euc1-prod.eu-gp-frankfurt-1"]})
servers.set_demo(demo, {"region": "eu", "name": "Europe", "entries": [], "older": [], "checked": t0}, now=t0 + timedelta(days=5))
pump(0.3)
game.settle()
pump(0.2)
check(len(servers.board.rows) == 4 and servers.board.rows[0]["city"] == "Frankfurt", "the board lists every server, lowest first")
check(servers.board.height() >= servers.board.HEAD + 4 * servers.board.ROW, f"the board is tall enough for its rows ({servers.board.height()} px)")
check(servers.cards["server"].value.text() == "25 ms" and "Frankfurt" in servers.cards["server"].sub.text(),
      f"the 'Your server' card shows VALORANT's pick ({servers.cards['server'].value.text()})")
check(servers.cards["steady"].value.text() == "24–26 ms" and "steady" in servers.cards["steady"].sub.text(),
      f"the steadiness card shows the spread ({servers.cards['steady'].value.text()} / {servers.cards['steady'].sub.text()})")
check(servers.insights.count() >= 2, f"insights are shown ({servers.insights.count()})")
check(servers.status_badge.isVisible() and servers.status_badge.text() == "All good", "Riot status: All good")
check(servers.width() <= 900 and servers.board.width() >= 500, f"the board fits a 900 px window ({servers.board.width()} px)")
cards = [c for c in servers.cards.values()]
check(all(c.isVisible() and c.height() < 160 for c in cards), f"stat cards are compact ({[c.height() for c in cards]})")
win.resize(1280, 800)
pump(0.3)
check(servers.board.width() >= 900, f"the board grows with the window ({servers.board.width()} px)")
servers.set_demo([], None)
pump(0.2)
check(servers.cards["server"].value.text() == "–" and servers.insights.count() == 1 and not servers.status_badge.isVisible(),
      "without measurements the tab explains what will appear")

win.quit()
print("\nALL PASSED" if not fails else f"\n{len(fails)} FAILED")
sys.exit(1 if fails else 0)
