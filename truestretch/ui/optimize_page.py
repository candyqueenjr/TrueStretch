"""Optimize Max page: a score, a live scan, and every optimization on its own row (what it is now, what it should
be, why) with Apply / Undo per item, Apply selected, Undo all, filters, and a Diagnostics tab with the full
technical report. Scanning and applying run in the background, so the window never freezes."""

import threading
from datetime import datetime

from PySide6.QtCore import QObject, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWidgets import QCheckBox, QFrame, QLabel, QPlainTextEdit, QProgressBar, QTabWidget, QWidget

from .. import optimizer as opt
from ..paths import log
from . import icons
from .base_page import Page
from .responsive import Reflow
from .theme import button_font, palette
from .widgets import Badge, Card, Segmented, button, clear_layout, divider, hbox, label, vbox

STATE_BADGE = {
    opt.DONE: ("Optimized", "success"), opt.IMPROVE: ("Can improve", "warning"), opt.OPTIONAL: ("Your choice", "info"),
    opt.INFO: ("Check", "info"), opt.UNAVAILABLE: ("Not available", "info"), opt.IN_GAME: ("Manual", "accent"),
}
LEVEL = {3: "High", 2: "Medium", 1: "Low"}
FILTERS = [("all", "All"), ("improve", "Can improve"), ("optional", "Your choice"), ("done", "Optimized"),
           ("info", "Info"), ("in_game", "Manual")]


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
        self.check.setChecked(item.can_apply and item.state == opt.IMPROVE)
        self.check.setEnabled(item.can_apply)
        self.check.setVisible(item.can_apply)
        self.check.toggled.connect(page.update_count)

        badge_text, kind = STATE_BADGE[item.state]
        top = hbox(label(item.title, "H3"), spacing=8)
        top.addWidget(Badge(badge_text.upper(), kind))
        if item.impact and item.state != opt.UNAVAILABLE:
            top.addWidget(Badge(f"{item.impact.upper()} · {LEVEL[item.level].upper()}",
                                "accent" if item.level == 3 else "info"))
        if item.id in changed:
            top.addWidget(Badge("CHANGED", "info"))
        top.addStretch(1)
        text = vbox(top, spacing=4)
        if item.why:
            text.addWidget(label(item.why, "Muted", wrap=True))
        extra = [x for x in (item.note, item.blocked) if x]
        if extra:
            text.addWidget(label("  ·  ".join(extra), "Faint", wrap=True))
        if result is not None:
            ok, msg = result
            r = label(("APPLIED AND VERIFIED" if ok else f"DIDN'T WORK: {msg}") +
                      (" — RESTART TO FINISH" if ok and item.restart else ""), "Caption")
            r.setStyleSheet(f"color:{p['success'] if ok else p['danger']};")
            r.setWordWrap(True)
            text.addWidget(r)
        if item.debug:
            details = label("\n".join(item.debug), "Mono", selectable=True)
            details.setWordWrap(True)
            details.hide()
            toggle = button("Technical details", None, "Link", lambda: details.setVisible(not details.isVisible()))
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
        if item.can_apply:
            actions.addWidget(button("Apply", None, None, lambda: page.apply([item.id])))
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
        self.filter = "all"
        self.bridge = _Bridge()
        self.bridge.progress.connect(self._on_progress)
        self.bridge.scanned.connect(self._on_scanned)
        self.bridge.applied.connect(self._on_applied)
        self.bridge.undone.connect(self._on_undone)

        self.add_header("Optimize Max", "Everything on this PC that affects VALORANT's FPS and input delay — each "
                        "change listed on its own, with what it is now, what it should be and why. Nothing changes "
                        "until you press Apply. Every change is verified, and everything can be undone.",
                        eyebrow="// Performance")

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
        for key, caption in (("improve", "Can improve"), ("optional", "Your choice"), ("done", "Optimized"),
                             ("in_game", "Manual")):
            v = label("–", "Stat")
            self.stat_labels[key] = v
            stats.addLayout(vbox(v, label(caption, "Caption"), spacing=0))
        self.btn_scan = button("Scan again", "refresh", None, self.scan)
        self.btn_undo_all = button("Undo all", "undo", None, lambda: self.undo(None))
        self.btn_apply = button("Apply selected", None, "Primary", self.apply_selected)
        buttons = hbox(self.btn_scan, self.btn_undo_all, self.btn_apply, spacing=8)
        top = Reflow(breakpoint=1000, spacing=26)
        top.add(score_box)
        top.add(stats)
        top.add(None)
        top.add(buttons)
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress_text = label("", "Caption")
        self.scan_info = label("", "Faint")
        self.scan_info.setWordWrap(True)
        summary.add(top, self.progress, self.progress_text, self.scan_info)
        self.content.addWidget(summary)

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.tabBar().setFont(button_font(10.5, spacing=1.6))
        changes = QWidget()
        changes.setObjectName("Transparent")
        self.filter_seg = Segmented(FILTERS, "all")
        self.filter_seg.changed.connect(self._set_filter)
        self.list = vbox(spacing=18)
        changes.setLayout(vbox(self.filter_seg, self.list, spacing=16, margins=(0, 16, 0, 0)))
        self.tabs.addTab(changes, "Changes")

        diag = QWidget()
        diag.setObjectName("Transparent")
        self.report = QPlainTextEdit()
        self.report.setReadOnly(True)
        self.report.setMinimumHeight(520)
        self.report.setStyleSheet('font-family:"Cascadia Mono","Consolas"; font-size:9pt;')
        bar = Reflow(breakpoint=640, spacing=10)
        bar.add(label("Full technical report: every value TrueStretch read, where it read it, and every change made "
                      "this session. Your Riot account ID is hidden.", "Muted", wrap=True), 1)
        bar.add(hbox(button("Copy", "copy", None, self.copy_report),
                     button("Save to Desktop", "download", None, self.save_report), spacing=8))
        diag.setLayout(vbox(bar, self.report, spacing=12, margins=(0, 16, 0, 0)))
        self.tabs.addTab(diag, "Diagnostics")
        self.content.addWidget(self.tabs)
        self.finish()
        self._set_busy(False)

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
        self._set_busy(False)
        self.render()

    def _set_busy(self, busy, text=""):
        self.busy = busy
        self.progress.setVisible(busy)
        self.progress_text.setVisible(busy)
        if busy:
            self.progress.setRange(0, 0)
            self.progress_text.setText(text.upper())
        for b in (self.btn_scan, self.btn_undo_all, self.btn_apply):
            b.setEnabled(not busy)
        if not busy:
            self.update_count()
            self.btn_undo_all.setEnabled(bool(self.opt.changed_ids()))

    # ---- rendering ------------------------------------------------------------
    def _set_filter(self, key):
        self.filter = key
        self.render()

    def _matches(self, item):
        if self.filter == "all":
            return True
        if self.filter == "info":
            return item.state in (opt.INFO, opt.UNAVAILABLE)
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
        self.score.setStyleSheet(f"font-size:44pt; color:{p['success'] if score >= 90 else p['text']};")
        when = self.opt.scanned_at.strftime("%H:%M:%S") if self.opt.scanned_at else "—"
        running = self.engine.running.get("valorant")
        self.scan_info.setText(f"Last scan {when}  ·  {len(items)} checks  ·  {len(changed)} change(s) by "
                               "TrueStretch can be undone" + ("  ·  VALORANT is running: game-file changes wait "
                                                              "until it's closed" if running else ""))
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
                        label(f"{todo} to improve" if todo else ("All good" if all_good else ""), "Caption"),
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
            self.list.addWidget(label("Nothing in this filter.", "Muted"))
        self.update_count()
        self.btn_undo_all.setEnabled(bool(changed) and not self.busy)
        self.report.setPlainText(self.opt.report())

    def update_count(self):
        n = sum(1 for r in self.rows if r.item.can_apply and r.check.isChecked())
        self.btn_apply.setText(f"Apply selected ({n})" if n else "Apply selected")
        self.btn_apply.setEnabled(bool(n) and not self.busy)
        self.btn_apply.updateGeometry()

    # ---- actions (background) --------------------------------------------------
    def apply_selected(self):
        self.apply([r.item.id for r in self.rows if r.item.can_apply and r.check.isChecked()])

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
        good = sum(1 for _, ok, _ in results if ok)
        bad = len(results) - good
        restart = any(ok and item.restart for item, ok, _ in results)
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
                done = []
            self.bridge.undone.emit(done)

        threading.Thread(target=work, name="optimize-undo", daemon=True).start()

    def _on_undone(self, done):
        self._set_busy(False)
        self.results = {}
        self.engine.notify("success", f"{len(done)} change(s) put back to how they were.")
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
        pass


def _note(text):
    w = QFrame()
    w.setObjectName("Transparent")
    ic = QLabel()
    ic.setPixmap(icons.pixmap("info", palette()["info"], 16))
    lay = hbox(ic, label(text, "Muted", wrap=True), spacing=10, margins=(20, 0, 20, 14))
    lay.setStretch(1, 1)
    w.setLayout(lay)
    return w
