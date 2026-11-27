"""Optimize Max page: a score, a live scan, and every optimization on its own row (what it is now, what it should
be, why) with Undo per item, Optimize (selected), filters and the technical report. After Optimize a result card
explains what changed and what it improves; "Your changes" lists everything TrueStretch changed (with Undo per
change and a two-step Undo all); changes that need a restart are reminded until Windows has restarted.
Scanning, applying and undoing run in the background, so the window never freezes."""

import threading
from datetime import datetime

from PySide6.QtCore import QObject, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWidgets import (QCheckBox, QDialog, QFrame, QLabel, QPlainTextEdit, QProgressBar, QScrollArea,
                               QWidget)

from .. import optimizer as opt
from ..paths import log
from . import icons
from .base_page import Page
from .responsive import Reflow
from .theme import button_font, palette
from .widgets import Badge, Card, Segmented, button, clear_layout, divider, hbox, label, vbox

STATE_BADGE = {
    opt.DONE: ("Optimized", "success"), opt.IMPROVE: ("To do", "warning"), opt.OPTIONAL: ("Optional", "info"),
    opt.INFO: ("Info", "info"), opt.UNAVAILABLE: ("Not available", "info"), opt.IN_GAME: ("Set in game", "warning"),
}
LEVEL = {3: "High", 2: "Medium", 1: "Low"}
FILTERS = [("todo", "To do"), ("in_game", "Set in game"), ("optional", "Optional"), ("done", "Already optimal"),
           ("all", "Everything")]


class _Bridge(QObject):
    progress = Signal(int, int, str)
    scanned = Signal(object)
    applied = Signal(object)
    undone = Signal(object)


class ItemRow(QFrame):
    def __init__(self, page, item, changed, result=None):
        super().__init__()
        self.setObjectName("Transparent")
        self.item = item
        p = palette()
        self.check = QCheckBox()
        self.check.setChecked(item.can_apply and item.id in page.selected)
        self.check.setEnabled(item.can_apply)
        self.check.setVisible(item.can_apply)
        self.check.setToolTip("Include this change when you press Optimize")
        self.check.setAccessibleName(f"Include: {item.title}")
        self.check.toggled.connect(lambda on, iid=item.id: page.select(iid, on))

        badge_text, kind = STATE_BADGE[item.state]
        top = hbox(label(item.title, "H3"), spacing=8)
        top.addWidget(Badge(badge_text.upper(), kind))
        if item.id in changed:
            top.addWidget(Badge("CHANGED BY TRUESTRETCH", "info"))
        top.addStretch(1)
        text = vbox(top, spacing=4)
        if item.impact and item.state not in (opt.UNAVAILABLE, opt.DONE):
            text.addWidget(label(f"{item.impact} · {LEVEL[item.level].lower()} impact", "Faint"))
        if item.why:
            text.addWidget(label(item.why, "Muted", wrap=True))
        extra = [x for x in (item.note, item.blocked) if x]
        if extra:
            text.addWidget(label("  ·  ".join(extra), "Faint", wrap=True))
        if result is not None:
            ok, msg = result
            r = label(("Done and checked" if ok else f"Didn't work — {msg}") +
                      (" · restart your PC to finish" if ok and item.restart else ""), "H3")
            r.setStyleSheet(f"color:{p['success'] if ok else p['danger']};")
            r.setWordWrap(True)
            text.addWidget(r)
        if item.debug:
            details = label("\n".join(item.debug), "Mono", selectable=True)
            details.setWordWrap(True)
            details.hide()
            toggle = button("Technical details", None, "Subtle", lambda: details.setVisible(not details.isVisible()))
            toggle.setFont(button_font(9, spacing=1.4))
            text.addWidget(toggle, 0, Qt.AlignLeft)
            text.addWidget(details)

        values = hbox(spacing=18)
        for caption, value, color in (("NOW", item.current, p["text"]),
                                      ("TARGET", item.target, p["success"] if item.state == opt.DONE else p["text"])):
            col = vbox(label(caption, "Caption"), spacing=1)
            v = label(value, "H3")
            v.setWordWrap(True)
            v.setMinimumWidth(110)
            v.setMaximumWidth(210)
            v.setStyleSheet(f"color:{color};")
            col.addWidget(v)
            values.addLayout(col)
        actions = hbox(spacing=6)
        if item.id in changed:
            actions.addWidget(button("Undo", "undo", None, lambda: page.undo([item.id])))
        if item.link:
            actions.addWidget(button("Get driver", "external", None,
                                     lambda: QDesktopServices.openUrl(QUrl(item.link))))
        actions.addStretch(1)
        side = vbox(values, actions, spacing=10)
        side.addStretch(1)

        body = Reflow(breakpoint=700, spacing=18)
        body.add(text, 1)
        body.add(side)
        row = hbox(spacing=14, margins=(20, 16, 20, 16))
        holder = QWidget()
        holder.setObjectName("Transparent")
        holder.setFixedWidth(18)
        holder.setLayout(vbox(self.check, None))
        row.addWidget(holder)
        row.addWidget(body, 1)
        self.setLayout(row)


class OptimizePage(Page):
    def __init__(self, engine, window):
        super().__init__(engine, window)
        self.opt = opt.Optimizer(engine)
        self.results = {}
        self.rows = []
        self.busy = False
        self._scanned = False
        self.filter = "todo"
        self.selected = set()              # item ids ticked for Optimize - kept across filters and re-renders
        self.unticked = set()              # ids the player unticked on purpose (not re-ticked by the next scan)
        self.bridge = _Bridge()
        self.bridge.progress.connect(self._on_progress)
        self.bridge.scanned.connect(self._on_scanned)
        self.bridge.applied.connect(self._on_applied)
        self.bridge.undone.connect(self._on_undone)

        self.add_header("Optimize Max", "Fixes the Windows, driver and game settings that cost VALORANT FPS or add "
                        "input delay. Nothing changes until you press Optimize — every change is checked afterwards "
                        "and can be undone.", eyebrow="// Performance")

        summary = Card(padding=22, spacing=16, accent=True)
        self.score = label("–", "Stat")
        self.score.setStyleSheet("font-size:44pt;")
        self.score_bar = QProgressBar()
        self.score_bar.setRange(0, 100)
        self.score_bar.setTextVisible(False)
        self.score_bar.setFixedWidth(180)
        score_box = vbox(label("Optimization score", "Caption"),
                         hbox(self.score, label("/100", "Muted"), None, spacing=6), self.score_bar, spacing=2)
        self.stat_labels = {}
        stats = hbox(spacing=30)
        for key, caption in (("improve", "To do"), ("in_game", "Set in game"), ("optional", "Optional"),
                             ("done", "Already optimal")):
            v = label("–", "Stat")
            self.stat_labels[key] = v
            stats.addLayout(vbox(v, label(caption, "Caption"), spacing=0))
        self.btn_scan = button("Scan again", "refresh", "Ghost", self.scan)
        self.btn_changes = button("Your changes", "undo", "Ghost", self.show_changes,
                                  "Everything TrueStretch changed on this PC — undo one change or all of them")
        self.btn_apply = button("Optimize", None, "Primary", self.apply_selected)
        buttons = hbox(None, self.btn_scan, self.btn_changes, self.btn_apply, spacing=8)
        # Wide: score · counts · … · buttons. Narrow (< 1000 px): score and counts stay side by side, only the
        # buttons move under them - the card used to stack all four and grow past 300 px tall.
        numbers = hbox(score_box, 26, stats, None, spacing=0)
        top = Reflow(breakpoint=1000, spacing=18)
        top.add(numbers, 1)
        top.add(buttons)
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress_text = label("", "Caption")
        self.scan_info = label("", "Faint")
        self.scan_info.setWordWrap(True)
        self.restart_note = label("", "H3", wrap=True)
        self.restart_note.hide()
        summary.add(top, self.progress, self.progress_text, self.scan_info, self.restart_note)
        self.content.addWidget(summary)
        self.last_run = None               # what the last Optimize did, for the result card (until dismissed)
        self.result_card = None
        self.changes_dialog = None

        self.filter_seg = Segmented(FILTERS, "todo")
        self.filter_seg.changed.connect(self._set_filter)
        report_btn = button("Technical report", "copy", "Ghost", self.show_report,
                            "Every value TrueStretch read and every change it made — for bug reports")
        bar = Reflow(breakpoint=640, spacing=10)
        bar.add(self.filter_seg)
        bar.add(None)
        bar.add(report_btn)
        self.list = vbox(spacing=18)
        self.content.addLayout(vbox(bar, self.list, spacing=16))
        self.finish()
        self._set_busy(False)

    def select(self, item_id, on):
        if on:
            self.selected.add(item_id)
            self.unticked.discard(item_id)
        else:
            self.selected.discard(item_id)
            self.unticked.add(item_id)
        self.update_count()

    def _sync_selection(self):
        """After a scan: everything that can be fixed is ticked, except what the player unticked themselves."""
        applicable = {i.id for i in self.opt.items if i.can_apply}
        todo = {i.id for i in self.opt.items if i.can_apply and i.state == opt.IMPROVE}
        self.selected = (self.selected & applicable) | (todo - self.unticked)

    def show_report(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("TrueStretch — Technical report")
        dialog.setWindowFlag(Qt.WindowContextHelpButtonHint, False)
        dialog.resize(860, 620)
        report = QPlainTextEdit(self.opt.report())
        report.setReadOnly(True)
        report.setStyleSheet('font-family:"Cascadia Mono","Consolas"; font-size:9pt;')
        dialog.setLayout(vbox(
            label("Every value TrueStretch read, where it read it, and every change made this session. Your Riot "
                  "account ID is hidden.", "Muted", wrap=True),
            report,
            hbox(button("Copy", "copy", None, self.copy_report),
                 button("Save to Desktop", "download", None, self.save_report), None,
                 button("Close", None, None, dialog.accept), spacing=8),
            spacing=12, margins=(20, 18, 20, 16)))
        dialog.exec()

    # ---- scanning (background) ----------------------------------------------
    def showEvent(self, event):
        super().showEvent(event)
        if not self._scanned and not self.busy:
            self.scan()

    def scan(self):
        if self.busy:
            return
        self._set_busy(True, "Starting scan")

        def work():
            try:
                self.opt.scan(lambda i, n, text: self.bridge.progress.emit(i, n, text))
            except Exception:
                log.exception("Optimize scan failed")
            self.bridge.scanned.emit(None)

        threading.Thread(target=work, name="optimize-scan", daemon=True).start()

    def _on_progress(self, i, n, text):
        self.progress.setRange(0, n)
        self.progress.setValue(i)
        self.progress_text.setText(f"CHECKING {i + 1}/{n} · {text.upper()}" if i < n else "DONE")

    def _on_scanned(self, _):
        self._scanned = True
        self._sync_selection()
        self._set_busy(False)
        self.render()

    def _set_busy(self, busy, text=""):
        self.busy = busy
        self.progress.setVisible(busy)
        self.progress_text.setVisible(busy)
        if busy:
            self.progress.setRange(0, 0)
            self.progress_text.setText(text.upper())
        for b in (self.btn_scan, self.btn_changes, self.btn_apply):
            b.setEnabled(not busy)
        if not busy:
            self.update_count()
            self._update_changes_button()

    # ---- rendering ------------------------------------------------------------
    def _set_filter(self, key):
        self.filter = key
        self.render()

    def _matches(self, item):
        if self.filter == "all":
            return True
        if self.filter == "todo":
            return item.state in (opt.IMPROVE, opt.IN_GAME)
        return item.state == self.filter

    def render(self):
        items = self.opt.items
        changed = self.opt.changed_ids()
        clear_layout(self.list)
        self.rows = []
        p = palette()
        counts = {k: sum(1 for i in items if i.state == k) for k in ("improve", "optional", "done", "in_game")}
        for k, v in counts.items():
            self.stat_labels[k].setText(str(v) if items else "–")
        self.stat_labels["improve"].setStyleSheet(f"color:{p['warning'] if counts['improve'] else p['success']};")
        score = self.opt.score() if items else 0
        self.score.setText(str(score) if items else "–")
        self.score_bar.setValue(score)
        tone = p["success"] if score >= 90 else (p["warning"] if score >= 70 else p["danger"])
        self.score.setStyleSheet(f"font-size:44pt; color:{tone if items else p['text']};")
        self.score_bar.setStyleSheet(f"QProgressBar::chunk {{ background:{tone}; }}")
        self.score_bar.setToolTip("100 = every setting TrueStretch can check is at its best value for VALORANT. "
                                  "Big wins (input delay, FPS) count more than small ones.")
        self._render_scan_info()
        self.result_card = None
        if self.last_run:
            self.result_card = ResultCard(self, self.last_run)
            self.list.addWidget(self.result_card)
        order = {opt.IMPROVE: 0, opt.OPTIONAL: 1, opt.INFO: 2, opt.IN_GAME: 3, opt.DONE: 4, opt.UNAVAILABLE: 5}
        shown_any = False
        for group in opt.GROUPS:
            group_items = [i for i in items if i.group == group and self._matches(i)]
            if not group_items:
                continue
            shown_any = True
            group_items.sort(key=lambda i: (order[i.state], -i.level))
            card = Card(padding=0, spacing=0)
            todo = sum(1 for i in group_items if i.state == opt.IMPROVE)
            all_good = all(i.state in (opt.DONE, opt.UNAVAILABLE) for i in group_items)
            head = hbox(label(group, "H2"), None,
                        label(f"{todo} to do" if todo else ("All good" if all_good else ""), "Caption"),
                        margins=(20, 16, 20, 14))
            card.body.addLayout(head)
            if group == "Inside VALORANT":
                card.body.addWidget(_note("Read from your last VALORANT session. These live in your Riot account, "
                                          "so only the game can change them — set each one as shown."))
            elif group.startswith("Inside"):
                card.body.addWidget(_note("These settings can only be changed inside that program. Set each one "
                                          "as shown — TrueStretch can't do it for you safely."))
            for item in group_items:
                card.body.addWidget(divider())
                row = ItemRow(self, item, changed, self.results.get(item.id))
                self.rows.append(row)
                card.body.addWidget(row)
            self.list.addWidget(card)
        if not shown_any and items:
            empty = Card(padding=24)
            if self.filter == "todo":
                empty.add(hbox(_icon("check-circle", p["success"], 24),
                               vbox(label("Nothing left to do", "H2"),
                                    label("Every setting TrueStretch can check is already at its best for VALORANT. "
                                          "Optional changes are under Optional.", "Muted", wrap=True), spacing=3),
                               None, spacing=14))
            else:
                empty.add(label("Nothing here right now.", "Muted"))
            self.list.addWidget(empty)
        self.update_count()
        self._update_changes_button()

    def _update_changes_button(self):
        n = len(self.opt.changed_ids())
        self.btn_changes.setText(f"Your changes ({n})" if n else "Your changes")
        self.btn_changes.setEnabled(bool(n) and not self.busy)
        self.btn_changes.updateGeometry()

    def show_changes(self):
        if not self.opt.changed_ids():
            return
        self.changes_dialog = ChangesDialog(self)
        self.changes_dialog.exec()
        self.changes_dialog = None

    def _show_result(self):
        if self.result_card is not None:
            self.ensureWidgetVisible(self.result_card, 0, 40)

    def dismiss_result(self):
        self.last_run = None
        self.render()

    def _render_scan_info(self):
        items, changed = self.opt.items, self.opt.changed_ids()
        when = self.opt.scanned_at.strftime("%H:%M") if self.opt.scanned_at else "—"
        undo = (f"{len(changed)} change{'s' if len(changed) != 1 else ''} by TrueStretch can be undone" if changed
                else "nothing to undo")
        running = self.engine.running.get("valorant")
        self.scan_info.setText(f"Last scan {when}  ·  {len(items)} checks  ·  {undo}"
                               + ("  ·  VALORANT is running: game-file changes wait until it's closed"
                                  if running else ""))
        pending = self.opt.restart_pending()
        self.restart_note.setVisible(bool(pending))
        if pending:
            self.restart_note.setText("Restart your PC to finish: " + ", ".join(pending[:4])
                                      + (f" and {len(pending) - 4} more" if len(pending) > 4 else ""))
            self.restart_note.setStyleSheet(f"color:{palette()['warning']};")

    def _applicable_selected(self):
        return [i.id for i in self.opt.items if i.can_apply and i.id in self.selected]

    def update_count(self):
        n = len(self._applicable_selected())
        self.btn_apply.setText(f"Optimize ({n})" if n else "Optimize")
        self.btn_apply.setEnabled(bool(n) and not self.busy)
        self.btn_apply.updateGeometry()

    # ---- actions (background) --------------------------------------------------
    def apply_selected(self):
        self.apply(self._applicable_selected())

    def apply(self, ids):
        if not ids or self.busy:
            return
        self._set_busy(True, f"Applying {len(ids)} change(s) and checking each one")
        hwnd = int(self.window.winId())

        def work():
            try:
                results = self.opt.apply(ids, hwnd)
            except Exception as exc:
                log.exception("Optimize apply failed")
                results = exc
            self.bridge.applied.emit(results)

        threading.Thread(target=work, name="optimize-apply", daemon=True).start()

    def _on_applied(self, results):
        self._set_busy(False)
        if isinstance(results, Exception):
            self.engine.notify("error", f"Couldn't apply: {results}")
            results = []
        self.results = {item.id: (ok, msg) for item, ok, msg in results}
        self._sync_selection()
        good = sum(1 for _, ok, _ in results if ok)
        bad = len(results) - good
        restart = any(ok and item.restart for item, ok, _ in results)
        self.last_run = summarize(results) if results else None
        if self.last_run:                  # on a small window the card is below the fold: bring it into view
            QTimer.singleShot(0, self._show_result)
        if results:
            self.engine.notify("success" if not bad else "warning",
                               f"{good} change(s) applied and verified" + (f", {bad} didn't work" if bad else "")
                               + (". Restart your PC to finish." if restart else "."))
        self.render()

    def undo(self, ids):
        if self.busy:
            return
        self._set_busy(True, "Putting the original values back")
        hwnd = int(self.window.winId())

        def work():
            try:
                done = self.opt.undo(ids, hwnd)
            except Exception:
                log.exception("Optimize undo failed")
                done = None
            self.bridge.undone.emit(done)

        threading.Thread(target=work, name="optimize-undo", daemon=True).start()

    def _on_undone(self, done):
        self._set_busy(False)
        self.results = {}
        self.last_run = None
        failed = list(self.opt.last_undo_failed)
        if done is None:
            self.engine.notify("error", "Undo didn't work — nothing was changed. Details are in the Technical report.")
        elif failed:
            self.engine.notify("warning", f"{len(done)} change(s) put back. Couldn't put back right now: "
                                          + ", ".join(failed[:3]) + (" …" if len(failed) > 3 else "") + ".")
        else:
            self.engine.notify("success", f"{len(done)} change(s) put back to how they were.")
        self._sync_selection()
        self.render()

    def copy_report(self):
        QGuiApplication.clipboard().setText(self.opt.report())
        self.engine.notify("success", "Report copied — paste it into a bug report.")

    def save_report(self):
        from ..support import _desktop
        path = _desktop() / f"TrueStretch-optimize-report-{datetime.now():%Y%m%d-%H%M%S}.txt"
        path.write_text(self.opt.report(), encoding="utf-8")
        self.engine.notify("success", f"Saved {path.name} on your Desktop.")

    def refresh(self):
        if self._scanned and not self.busy:
            self._render_scan_info()          # keeps "VALORANT is running" current without a full re-render


def summarize(results):
    """What the result card shows: [(item, ok, msg)] -> {done: [item], failed: [(item, msg)], restart: [title],
    impacts: [(impact, count)] most common first, time}."""
    done = [item for item, ok, _ in results if ok]
    failed = [(item, msg) for item, ok, msg in results if not ok]
    impacts = {}
    for item in done:
        if item.impact:
            impacts[item.impact] = impacts.get(item.impact, 0) + 1
    return {"done": done, "failed": failed, "restart": [i.title for i in done if i.restart],
            "impacts": sorted(impacts.items(), key=lambda kv: (-kv[1], kv[0])), "time": datetime.now()}


class ResultCard(QFrame):
    """Shown at the top of the list after Optimize: the rows that were fixed leave the To do view, so without this
    the only feedback was a toast that disappears after a few seconds."""

    def __init__(self, page, run):
        super().__init__()
        self.setObjectName("Card")
        p = palette()
        done, failed = run["done"], run["failed"]
        total = len(done) + len(failed)
        ok_all = not failed
        if done and ok_all:
            title = f"{len(done)} change{'s' if len(done) != 1 else ''} done and checked"
        elif done:
            title = f"{len(done)} of {total} changes worked"
        else:
            title = "Nothing could be changed"
        head = hbox(_icon("check-circle" if done else "alert", p["success"] if ok_all else p["warning"], 22),
                    label(title, "H2"), None,
                    button("Dismiss", None, "Subtle", page.dismiss_result), spacing=12)
        body = vbox(head, spacing=8, margins=(20, 16, 20, 16))
        if done:
            body.addWidget(label("TrueStretch read every setting back after changing it — these are in place now:",
                                 "Muted", wrap=True))
            if run["impacts"]:
                tags = hbox(spacing=8)
                for impact, count in run["impacts"][:4]:          # 4 fit in one line at 900 px
                    tags.addWidget(Badge(f"{impact.upper()} · {count}", "success"))
                tags.addStretch(1)
                body.addLayout(tags)
            names = ", ".join(i.title for i in done[:6]) + (f" and {len(done) - 6} more" if len(done) > 6 else "")
            body.addWidget(label(names, "Faint", wrap=True))
        for item, msg in failed[:5]:
            r = label(f"✖  {item.title} — {msg or 'Windows did not accept the change'}", "Muted", wrap=True)
            r.setStyleSheet(f"color:{p['danger']};")
            body.addWidget(r)
        if run["restart"]:                 # the score card keeps the reminder until Windows has restarted
            body.addWidget(label("Some changes finish after a restart — see the reminder above.", "Muted",
                                 wrap=True))
        if done:
            body.addWidget(label("Play a match to see the difference: the \"Your last match\" row on this page "
                                 "compares your FPS before and after Optimize Max. Changed your mind? Press Your "
                                 "changes and undo any of them.", "Faint", wrap=True))
        self.setLayout(body)


class ChangesDialog(QDialog):
    """Every change TrueStretch made that is still in place: what, when, from → to, Undo per change, and Undo all
    behind a second click (it used to be one click on the main card, with no way back)."""

    def __init__(self, page):
        super().__init__(page)
        self.page = page
        self.setWindowTitle("TrueStretch — Your changes")
        self.setWindowFlag(Qt.WindowContextHelpButtonHint, False)
        self.resize(720, 560)
        self.changes = page.opt.changes()
        n = len(self.changes)
        rows = vbox(spacing=0)
        self.undo_buttons = {}
        for c in self.changes:
            rows.addWidget(divider())
            rows.addWidget(self._row(c))
        rows.addStretch(1)
        holder = QWidget()
        holder.setObjectName("Transparent")
        holder.setLayout(rows)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(holder)
        self.btn_all = button(f"Undo all {n}", "undo", "Ghost", self._undo_all_clicked)
        self.confirm_text = label("", "Faint", wrap=True)
        self.setLayout(vbox(
            label(f"{n} change{'s' if n != 1 else ''} by TrueStretch", "H2"),
            label("Everything Optimize Max changed on this PC, newest first. Undo puts the exact value from before "
                  "back — even if a later scan no longer shows the setting.", "Muted", wrap=True),
            scroll, self.confirm_text,
            hbox(self.btn_all, None, button("Close", None, None, self.reject), spacing=8),
            spacing=12, margins=(22, 20, 22, 18)))

    def _row(self, c):
        w = QFrame()
        w.setObjectName("Transparent")
        text = vbox(spacing=2)
        top = hbox(label(c["title"], "H3"), spacing=8)
        if c["restart_pending"]:
            top.addWidget(Badge("RESTART TO FINISH", "warning"))
        top.addStretch(1)
        text.addLayout(top)
        bits = []
        if c["from"] or c["to"]:
            bits.append(f"{c['from'] or '?'} → {c['to'] or '?'}")
        if c["group"]:
            bits.append(c["group"])
        if c["time"]:
            bits.append("changed " + _when(c["time"]))
        if bits:
            text.addWidget(label("  ·  ".join(bits), "Faint", wrap=True))
        undo = button("Undo", "undo", None, lambda _checked=False, iid=c["id"]: self._undo([iid]))
        undo.setAccessibleName(f"Undo: {c['title']}")
        self.undo_buttons[c["id"]] = undo
        lay = hbox(text, undo, spacing=12, margins=(4, 10, 4, 10))
        lay.setStretch(0, 1)
        w.setLayout(lay)
        return w

    def _undo_all_clicked(self):
        if not self.btn_all.property("armed"):
            self.btn_all.setProperty("armed", True)
            self.btn_all.setText(f"Yes, undo all {len(self.changes)}")
            self.confirm_text.setText("Every setting above goes back to how it was before TrueStretch. Click again "
                                      "to confirm.")
            return
        self._undo(None)

    def _undo(self, ids):
        self.accept()
        self.page.undo(ids)


def _when(t):
    today = datetime.now().date()
    if t.date() == today:
        return f"today {t:%H:%M}"
    return f"{t:%d %b %Y}".lstrip("0")


def _icon(name, color, size):
    ic = QLabel()
    ic.setPixmap(icons.pixmap(name, color, size))
    ic.setAlignment(Qt.AlignTop)
    return ic


def _note(text):
    w = QFrame()
    w.setObjectName("Transparent")
    ic = QLabel()
    ic.setPixmap(icons.pixmap("info", palette()["info"], 16))
    lay = hbox(ic, label(text, "Muted", wrap=True), spacing=10, margins=(20, 0, 20, 14))
    lay.setStretch(1, 1)
    w.setLayout(lay)
    return w
