"""Matches: how every finished match really ran (VALORANT's own statistics), kept by TrueStretch - summary cards,
an FPS chart of recent matches, what changed things (Optimize Max, stretch size), and the full list."""

import threading

from PySide6.QtCore import QObject, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import QHeaderView, QLabel, QTreeWidget, QTreeWidgetItem, QWidget

from .. import history
from ..paths import log
from . import icons
from .base_page import Page
from .responsive import ResponsiveGrid
from .theme import palette
from .widgets import Card, StatCard, button, clear_layout, hbox, label, vbox

CHART_MATCHES = 30


class _Bridge(QObject):
    loaded = Signal(object)


class FpsChart(QWidget):
    """Average FPS per match as bars, newest on the right. Matches with Optimize Max changes active are drawn in
    the success colour, the others in the muted colour; the dashed line is the average of the matches shown."""

    def __init__(self):
        super().__init__()
        self.records = []
        self.setMinimumHeight(170)
        self.setMouseTracking(True)
        self._bars = []

    def sizeHint(self):
        return QSize(600, 190)

    def set_records(self, records):
        self.records = records[-CHART_MATCHES:]
        self.update()

    def mouseMoveEvent(self, event):
        for rect, rec in self._bars:
            if rect.contains(event.position()):
                when = history._parse(rec["started"])
                self.setToolTip(f"{history.map_name(rec.get('map'))} · {when:%d %b, %H:%M} · {rec['fps']:.0f} FPS"
                                + (" · Optimize Max on" if rec.get("optimized") else "")
                                + (f" · {rec['stretch']}" if rec.get("stretch") else ""))
                return
        self.setToolTip("")

    def paintEvent(self, _event):
        p = palette()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, False)
        w, h = self.width(), self.height()
        left, bottom, top = 44, 22, 10
        if not self.records:
            painter.setPen(QColor(p["muted"]))
            painter.drawText(self.rect(), Qt.AlignCenter, "Your matches appear here after you play.")
            return
        top_fps = max(r["fps"] for r in self.records)
        scale_max = max(60.0, top_fps * 1.12)
        plot_h = h - top - bottom
        small = QFont(self.font())
        small.setPointSizeF(8.5)
        painter.setFont(small)
        grid = QColor(p["border"])
        for frac in (0.0, 0.5, 1.0):
            y = top + plot_h * (1 - frac)
            painter.setPen(grid)
            painter.drawLine(left, int(y), w, int(y))
            painter.setPen(QColor(p["faint"]))
            painter.drawText(QRectF(0, y - 8, left - 8, 16), Qt.AlignRight | Qt.AlignVCenter, f"{scale_max * frac:.0f}")
        n = len(self.records)
        slot = min(46.0, (w - left) / max(n, 1))         # few matches: narrow slots, lined up from the right
        start = w - slot * n
        bar_w = max(4.0, min(28.0, slot * 0.64))
        self._bars = []
        for i, rec in enumerate(self.records):
            bh = plot_h * rec["fps"] / scale_max
            x = start + i * slot + (slot - bar_w) / 2
            rect = QRectF(x, top + plot_h - bh, bar_w, bh)
            color = QColor(p["success"] if rec.get("optimized") else p["muted"])
            if i == n - 1:
                color = QColor(p["text"])
            painter.fillRect(rect, color)
            self._bars.append((QRectF(start + i * slot, top, slot, plot_h), rec))
        avg = sum(r["fps"] for r in self.records) / n
        y = top + plot_h * (1 - avg / scale_max)
        pen = painter.pen()
        pen.setColor(QColor(p["accent"]))
        pen.setStyle(Qt.DashLine)
        painter.setPen(pen)
        painter.drawLine(left, int(y), w, int(y))
        painter.setPen(QColor(p["faint"]))
        painter.drawText(QRectF(left, h - bottom + 4, w - left, bottom - 4), Qt.AlignLeft | Qt.AlignVCenter,
                         f"Last {n} match{'es' if n != 1 else ''} · newest on the right · dashed line = average "
                         f"{avg:.0f} FPS")


class MatchesPage(Page):
    def __init__(self, engine, window):
        super().__init__(engine, window)
        self.records = []
        self.busy = False
        self._loaded = False
        self.bridge = _Bridge()
        self.bridge.loaded.connect(self._on_loaded)
        engine.history_changed.connect(self._on_history_changed)     # a method: disconnected when the page goes
        self.btn_refresh = button("Look for new matches", "refresh", "Ghost", self.load)
        self.add_header("Your matches", "How every match really ran, from VALORANT's own statistics: average FPS, "
                        "slow frames, game delay and what held the FPS back. TrueStretch keeps the history, and after "
                        "each match it tells you how it went.", right=self.btn_refresh, eyebrow="// Performance")

        self.cards = {k: StatCard(c) for k, c in (("matches", "Matches"), ("fps", "Average FPS"),
                                                  ("slow", "Slow frames"), ("latency", "Game delay"))}
        grid = ResponsiveGrid(min_width=190, max_cols=4, spacing=12)
        for card in self.cards.values():
            grid.add(card)
        self.content.addWidget(grid)

        chart_card = Card(padding=18, spacing=10)
        legend = hbox(label("FPS per match", "H2"), None, spacing=14)
        for color_key, text in (("success", "Optimize Max on"), ("muted", "Before Optimize Max"),
                                ("text", "Latest")):
            sw = QLabel()
            sw.setFixedSize(10, 10)
            sw.setProperty("swatch", color_key)
            legend.addWidget(sw)
            legend.addWidget(label(text, "Faint"))
        self.legend = legend
        self.chart = FpsChart()
        chart_card.add(legend, self.chart)
        self.content.addWidget(chart_card)

        self.insights_card = Card(padding=18, spacing=10)
        self.insights = vbox(spacing=10)
        self.insights_card.add(label("What changed your FPS", "H2"), self.insights)
        self.content.addWidget(self.insights_card)

        list_card = Card(padding=18, spacing=10)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["When", "Map", "Length", "Avg FPS", "Slow frames", "Game delay", "Limited by",
                                   "Stretch"])
        self.tree.setRootIsDecorated(False)
        self.tree.setMinimumHeight(320)
        self.tree.setSortingEnabled(False)
        header = self.tree.header()
        header.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        header.setStretchLastSection(True)
        for col, width in enumerate((150, 120, 80, 80, 100, 100, 170)):
            header.setSectionResizeMode(col, QHeaderView.Interactive)
            header.resizeSection(col, width)
        list_card.add(label("All matches", "H2"), self.tree)
        self.content.addWidget(list_card)
        self.finish()

    # ---- loading (background: reading VALORANT's logs can take a moment) -----

    def _on_history_changed(self):
        if self.isVisible():
            self.load()
        else:
            self._loaded = False

    def showEvent(self, event):
        super().showEvent(event)
        if not self._loaded and not self.busy:
            self.load()

    def load(self):
        if self.busy:
            return
        self.busy = True
        self.btn_refresh.setEnabled(False)

        def work():
            try:
                records, _ = history.refresh_for(self.engine)
            except Exception:
                log.exception("Loading the match history failed")
                records = history.load()
            self.bridge.loaded.emit(records)

        threading.Thread(target=work, name="match-history", daemon=True).start()

    def _on_loaded(self, records):
        self.busy = False
        self._loaded = True
        self.btn_refresh.setEnabled(True)
        self.records = records
        self.render()

    # ---- rendering ----------------------------------------------------------

    def render(self):
        p = palette()
        recs = self.records
        recent = recs[-20:]
        st = history.stats(recent)
        total = history.stats(recs)["minutes"]
        self.cards["matches"].set(str(len(recs)), (f"{total / 60:.1f} hours played" if total >= 60 else
                                                   f"{total:.0f} minutes played") if recs else "Play a match to start")
        self.cards["fps"].set(f"{st['fps']:.0f}" if st["fps"] else "–", "last 20 matches" if recs else "")
        self.cards["slow"].set(f"{st['slow_share'] * 100:.1f}%" if st["slow_share"] is not None else "–",
                               "of frames under 60 FPS")
        self.cards["latency"].set(f"{st['latency']:.1f} ms" if st["latency"] is not None else "–",
                                  "VALORANT's own engine latency")
        for i in range(self.legend.count()):
            w = self.legend.itemAt(i).widget()
            if w is not None and w.property("swatch"):
                w.setStyleSheet(f"background:{p[w.property('swatch')]};")
        self.chart.set_records(recs)
        self._render_insights(recs)
        self.tree.clear()
        for rec in reversed(recs):
            when = history._parse(rec["started"])
            slow = rec.get("slow_share")
            lat = rec.get("latency")
            item = QTreeWidgetItem([
                f"{when:%d %b %Y, %H:%M}" if when else "?", history.map_name(rec.get("map")),
                f"{rec.get('minutes') or 0:.0f} min", f"{rec['fps']:.0f}",
                f"{slow * 100:.1f}%" if slow is not None else "–", f"{lat:.1f} ms" if lat is not None else "–",
                history.LIMIT_TEXT.get(rec.get("limit"), "unknown"), rec.get("stretch") or "–"])
            if rec.get("optimized"):
                item.setToolTip(0, "Optimize Max changes were active in this match")
                item.setIcon(0, icons.icon("wand", p["success"], 14))
            self.tree.addTopLevelItem(item)
        if not recs:
            item = QTreeWidgetItem(["No finished matches found yet — play one and it shows up here."] + [""] * 7)
            item.setFlags(Qt.NoItemFlags)
            self.tree.addTopLevelItem(item)

    def _render_insights(self, recs):
        clear_layout(self.insights)
        p = palette()
        lines = []
        on = [r for r in recs if r.get("optimized")][-10:]
        off = [r for r in recs if not r.get("optimized")][-10:]
        if on and off:
            a, b = history.stats(on)["fps"], history.stats(off)["fps"]
            if a and b:
                change = a / b - 1
                lines.append(("wand", p["success"] if change >= 0 else p["warning"],
                              f"With Optimize Max: {a:.0f} FPS on average ({len(on)} matches) vs {b:.0f} FPS before "
                              f"({len(off)} matches) — {change * 100:+.0f}%. Maps and modes change FPS too, so this "
                              "gets more accurate with every match."))
        by_size = {}
        for r in recs:
            if r.get("stretch"):
                by_size.setdefault(r["stretch"], []).append(r)
        if len(by_size) > 1:
            parts = [f"{size}: {history.stats(rs)['fps']:.0f} FPS ({len(rs)})" for size, rs in
                     sorted(by_size.items(), key=lambda kv: -len(kv[1]))[:4]]
            lines.append(("stretch", p["info"], "By stretch size — " + " · ".join(parts) + "."))
        limited = [r.get("limit") for r in recs[-10:] if r.get("limit")]
        if limited:
            top = max(set(limited), key=limited.count)
            share = limited.count(top) / len(limited)
            advice = {
                "gpu": "Lower Material/Texture quality or turn off anti-aliasing in VALORANT for more FPS.",
                "cpu": "Close background programs while you play (Optimize Max lists them), and keep the laptop "
                       "plugged in.",
                "both": "Both the processor and the graphics card were near their limit.",
                "cap": "Your in-game FPS limit set the FPS — that's fine if it's at or above your refresh rate.",
            }[top]
            lines.append(("pulse", p["muted"], f"In {share * 100:.0f}% of your last {len(limited)} matches the FPS "
                          f"was limited by your {history.LIMIT_TEXT[top]}. {advice}"))
        if not lines:
            lines.append(("info", p["muted"], "Play a few matches before and after a change (Optimize Max, a new "
                          "stretch size, a driver update) and TrueStretch shows here what it did to your FPS."))
        for name, color, text in lines:
            ic = QLabel()
            ic.setPixmap(icons.pixmap(name, color, 18))
            ic.setAlignment(Qt.AlignTop)
            row = hbox(ic, spacing=12)
            row.addWidget(label(text, "Muted", wrap=True), 1)
            self.insights.addLayout(row)

    def refresh(self):
        pass
