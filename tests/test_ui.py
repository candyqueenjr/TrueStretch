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

from PySide6.QtWidgets import QApplication, QLabel         # noqa: E402

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
# ---- background steps keep the window alive (2.2.0) -------------------------------
import threading                                              # noqa: E402
win.resize(1280, 800); pump(0.1)
seen = {}


def slow_work():
    seen["thread"] = threading.current_thread().name
    time.sleep(0.3)
    return "ok"


def done(result, error):
    seen["result"], seen["error"], seen["done_thread"] = result, error, threading.current_thread().name


started = win.run_background("Turning monitor drivers off", slow_work, done)
check(started and win.play_btn.text() == "Working…" and not win.play_btn.isEnabled(),
      "while a background step runs, PLAY says Working… and is disabled")
check(win.top_status.text().upper().startswith("TURNING MONITOR DRIVERS OFF"),
      f"the top badge shows the step ({win.top_status.text()})")
check(win.run_background("Second", slow_work, done) is False, "a second step is refused while one runs")
pump(0.8)
check(seen.get("result") == "ok" and seen.get("error") is None, f"the result reaches done() ({seen})")
check(seen.get("thread") != "MainThread" and seen.get("done_thread") == "MainThread",
      f"work ran off the UI thread, done() on it ({seen.get('thread')}, {seen.get('done_thread')})")
check(win._busy is None and win.play_btn.text() != "Working…", "PLAY is back to normal afterwards")


def failing_work():
    raise OSError("pnputil said no")


seen.clear()
win.run_background("Turning monitor drivers off", failing_work, done)
pump(0.5)
check(isinstance(seen.get("error"), OSError) and seen.get("result") is None,
      "an exception in the worker reaches done() as error")
check(win._busy is None, "busy state cleared after a failure too")

# ---- display reads are cached inside a refresh (2.2.0) ----------------------------
from truestretch import display as _display, readcache     # noqa: E402
counts = {"displays": 0, "monitors": 0}
orig_ld, orig_mon = _display._list_displays, displayconfig._monitors


def counting_ld():
    counts["displays"] += 1
    return orig_ld()


def counting_mon():
    counts["monitors"] += 1
    return orig_mon()


_display._list_displays, displayconfig._monitors = counting_ld, counting_mon
try:
    win.navigate("game:valorant"); pump(0.1)
    counts.update(displays=0, monitors=0)
    win.refresh_all(); pump(0.05)
    check(counts["displays"] <= 1 and counts["monitors"] <= 1,
          f"one refresh of the VALORANT page lists the displays {counts['displays']}x and queries monitors "
          f"{counts['monitors']}x (was 5 / 8)")
    counts.update(displays=0, monitors=0)
    win.navigate("mypc"); pump(0.1)
    check(counts["displays"] <= 1 and counts["monitors"] <= 1,
          f"opening My PC lists the displays {counts['displays']}x and queries monitors {counts['monitors']}x "
          "(was 6 / 9)")
    check(not readcache.active(), "no cache is left active after a refresh")
finally:
    _display._list_displays, displayconfig._monitors = orig_ld, orig_mon

# ---- Optimize: Set in game filter (2.2.0) -----------------------------------------
win.navigate("optimize"); pump(0.1)
opt_page = win.pages["optimize"]
check("in_game" in opt_page.filter_seg.buttons and opt_page.filter_seg.buttons["in_game"].text() == "Set in game",
      "Optimize has a Set in game filter")
win.resize(900, 620); pump(0.2)
seg = opt_page.filter_seg
check(all(b.width() >= b.sizeHint().width() - 2 for b in seg.buttons.values()) and seg.width() <= 880,
      f"the five filter buttons fit at 900 px (segment {seg.width()} px)")
win.resize(1280, 800); pump(0.1)

# ---- Color tab (2.3.0): Game Color ------------------------------------------------
# A fake driver: the real one is exercised in test_gamecolor.py; nothing on this PC changes here.
from truestretch import gamecolor                           # noqa: E402
from truestretch.gamecolor import GameColor, Screen         # noqa: E402


class _FakeColor:
    def __init__(self):
        self.level, self.sets = 50, []

    def find(self, device):
        return self, Screen("nvidia", "FAKE", device or "FAKE", self.level, 50, 0, 100), None

    def make(self, name):
        return self

    def set_level(self, key, level):
        self.sets.append(level)
        self.level = level


fake_color, front_exe = _FakeColor(), {"exe": None}
orig_find = gamecolor.find_screen
gamecolor.find_screen = fake_color.find
engine.color = GameColor(find=fake_color.find, make=fake_color.make, front=lambda: front_exe["exe"])
win.show()                                                  # win.quit() above hid it
try:
    for w, h in ((900, 620), (1280, 800)):
        win.resize(w, h); pump(0.1)
        win.navigate("game:valorant"); game.show_tab("color"); pump(0.3)
        ct = game.color
        check(game.tabs.tabText(game.tabs.currentIndex()) == "Color" and ct.isVisible(),
              f"the VALORANT page has a Color tab ({w} px)")
        check(ct.width() <= game.tabs.width() and ct.level.width() >= ct.level.sizeHint().width() - 2,
              f"the Color tab and its four strength buttons fit at {w} px")
    check(ct.state.text() == "Off" and not ct.toggle.isChecked(), "Game Color starts off")
    check("NVIDIA digital vibrance — normal 50 %, in VALORANT 75 %" in ct.screen_line.text(),
          f"the screen line says what will happen ({ct.screen_line.text()})")
    check(ct.try_btn.isEnabled(), "Preview is offered while VALORANT is closed")
    ct.toggle.setChecked(True); pump(0.1)
    check(engine.gs("valorant")["game_color"] is True, "the toggle is saved")
    check(ct.state.text().startswith("Ready"), "on but the game isn't in front: Ready")
    ct.level.buttons["strong"].click(); pump(0.1)
    check(engine.gs("valorant")["game_color_level"] == "strong" and "85 %" in ct.screen_line.text(),
          "Strong = 85 % and saved")
    check(ct.preview.percent == 70 and ct.preview.active, "the before/after strip follows the strength")
    engine.running["valorant"] = True
    front_exe["exe"] = "valorant-win64-shipping.exe"
    engine._tick_color(); pump(0.1)
    check(fake_color.level == 85 and engine.color_active(), "VALORANT in front: the boost is on")
    game.refresh(); pump(0.05)
    check(ct.state.text() == "On now" and not ct.try_btn.isEnabled(), "the tab says On now; no preview in game")
    check("normal 50 %" in ct.screen_line.text(), "while on, the tab still shows the normal level (not 85)")
    front_exe["exe"] = "explorer.exe"
    engine._tick_color()
    check(fake_color.level == 50 and not engine.color_active(), "alt-tab: back to normal")
    front_exe["exe"] = "valorant-win64-shipping.exe"
    engine._tick_color()
    engine.running["valorant"] = False
    engine._tick_color()
    check(fake_color.level == 50, "the game closing turns it off")
    engine._tick_color()
    check(fake_color.sets == [85, 50, 85, 50], f"no extra driver calls ({fake_color.sets})")
    ct.toggle.setChecked(False); pump(0.05)
finally:
    gamecolor.find_screen = orig_find

# Opening a tab refreshes it (Display used to keep what it had at the last engine change).
game.show_tab("resolution"); pump(0.05)
game.desktop_now.setText("")
game.show_tab("display"); pump(0.1)
check(game.desktop_now.text() != "", f"opening the Display tab fills it ({game.desktop_now.text()})")

# ---- Optimize (2.4.0): result card, Your changes, restart reminder ---------------------------------
from truestretch import optimizer as _opt                     # noqa: E402
from truestretch.ui import optimize_page as _op               # noqa: E402

win.navigate("optimize"); pump(0.1)
op = win.pages["optimize"]
for _ in range(600):
    pump(0.05)
    if op._scanned and not op.busy:
        break
saved_undo = op.opt._undo_data()                              # temp APPDATA: empty, but keep the rule
fx = [_opt.Item(f"fx{n}", "Windows", f"Fake {n}", "", "Off", "On", _opt.DONE, imp, 2, restart=(n == 2))
      for n, imp in enumerate(["More FPS", "More FPS", "Lower input delay", "Steadier FPS"])]
bad = _opt.Item("fxbad", "Network", "Fake broken", "", "Off", "On", _opt.IMPROVE, "Stable ping", 2)
op.last_run = _op.summarize([(i, True, "") for i in fx] + [(bad, False, "Windows still reports Off")])
op.filter = "todo"
op.render(); pump(0.1)
cards = [w for w in op.findChildren(_op.ResultCard) if w.isVisible()]
check(len(cards) == 1, "after Optimize a result card is shown on the To do view")
txt = " ".join(lb.text() for lb in cards[0].findChildren(QLabel)) if cards else ""
check("4 of 5 changes worked" in txt and "Fake broken" in txt and "Windows still reports Off" in txt
      and "after a restart" in txt, "it says what worked, what didn't (with the reason) and that a restart is needed")
check("MORE FPS · 2" in txt, "it counts what the changes improve")
win.resize(900, 620); pump(0.3)
card = cards[0] if cards else None
check(card is not None and card.width() <= op.viewport().width() and all(
    b.geometry().right() <= card.width() for b in card.findChildren(_op.Badge)),
    "the result card and its tags fit at 900 px")
op.verticalScrollBar().setValue(0)
op._show_result(); pump(0.1)
top = card.mapTo(op.viewport(), card.rect().topLeft()).y() if card else -1
check(card is not None and 0 <= top < op.viewport().height(), f"after Optimize the card is scrolled into view ({top})")
win.resize(1280, 800); pump(0.1)
op.dismiss_result(); pump(0.1)
check(not [w for w in op.findChildren(_op.ResultCard) if w.isVisible()], "Dismiss removes the card")

# Your changes: count on the button, list, two-step Undo all.
now = datetime.now().isoformat(timespec="seconds")
op.opt._save_undo({"game_mode": {"time": now, "title": "Game Mode", "from": "Off", "to": "On", "group": "Windows"},
                   "hags": {"time": now, "title": "GPU scheduling", "admin": True, "restart": True,
                            "undo_cmds": ["x"]}})
op.render(); pump(0.05)
check(op.btn_changes.text() == "Your changes (2)" and op.btn_changes.isEnabled(), "the button counts the changes")
check(op.restart_note.isVisible() and "GPU scheduling" in op.restart_note.text(),
      "the score card reminds to restart for a change that needs it")
asked = []
orig_undo = op.undo
op.undo = lambda ids: asked.append(ids)
dlg = _op.ChangesDialog(op)
dlg.show(); pump(0.1)
check(set(dlg.undo_buttons) == {"game_mode", "hags"}, "Your changes lists every change with its own Undo")
dtxt = " ".join(lb.text() for lb in dlg.findChildren(QLabel))
check("Off → On" in dtxt and "changed today" in dtxt and "RESTART TO FINISH" in dtxt,
      "each change shows from → to, when, and a pending restart")
dlg.btn_all.click(); pump(0.05)
check(asked == [] and dlg.btn_all.text().startswith("Yes, undo all"), "Undo all asks for a second click first")
dlg.btn_all.click(); pump(0.05)
check(asked == [None], "the second click undoes everything")
dlg2 = _op.ChangesDialog(op)
dlg2.show(); pump(0.05)
dlg2.undo_buttons["game_mode"].click(); pump(0.05)
check(asked[-1] == ["game_mode"], "Undo on one row undoes just that change")
op.undo = orig_undo
op.opt._save_undo(saved_undo)
op.render(); pump(0.05)
check(op.btn_changes.text() == "Your changes" and not op.btn_changes.isEnabled() and not op.restart_note.isVisible(),
      "no changes: button disabled, no reminder")

print("\nALL PASSED" if not fails else f"\n{len(fails)} FAILED")
sys.exit(1 if fails else 0)
