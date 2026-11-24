"""Servers tab of the VALORANT page: the ping board. VALORANT's own ping to every game server of the player's
region (measured by the game at every start, kept by TrueStretch), which server VALORANT prefers, how steady the
ping is between game starts, what to do about it, and Riot's current server notices for the region."""

import threading
import time

from PySide6.QtCore import QObject, QRectF, QSize, Qt, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QFont, QPainter
from PySide6.QtWidgets import QLabel, QWidget

from .. import ping
from ..paths import log
from . import icons
from .responsive import Reflow, ResponsiveGrid
from .theme import display_font, palette
from .widgets import Badge, Card, StatCard, button, clear_layout, hbox, label, vbox

STALE_SECONDS = 300             # re-read the game's logs when the tab is opened after this long
STATUS_SECONDS = 600            # ask Riot's status feed again after this long


class _Bridge(QObject):
    board = Signal(object)
    status = Signal(object, str)


class PingBoard(QWidget):
    """One row per server, lowest ping first: city, a bar for the ping now (with a thin mark at the typical value
    over the last two weeks), the milliseconds, and typical · best. VALORANT's preferred server and the lowest
    one are tagged."""

    ROW, HEAD = 34, 26

    def __init__(self):
        super().__init__()
        self.rows = []
        self.setMouseTracking(True)
        self._hits = []
        self._fit()

    def _fit(self):
        self.setMinimumHeight(self.HEAD + self.ROW * max(len(self.rows), 3) + 6)
        self.updateGeometry()

    def sizeHint(self):
        return QSize(600, self.minimumHeight())

    def set_board(self, b):
        self.rows = list(b["rows"]) if b else []
        self._fit()
        self.update()

    def mouseMoveEvent(self, event):
        for rect, r in self._hits:
            if rect.contains(event.position()):
                parts = [r["city"]]
                if r["now"] is not None:
                    parts.append(f"{r['now']} ms now ({ping.quality(r['now'])})")
                if r["typical"] is not None:
                    parts.append(f"typical {r['typical']:.0f} ms · best {r['best']} · worst {r['worst']} over "
                                 f"{r['samples']} game start{'s' if r['samples'] != 1 else ''}")
                if r["preferred"]:
                    parts.append("VALORANT's preferred server for you")
                self.setToolTip(" · ".join(parts))
                return
        self.setToolTip("")

    def paintEvent(self, _event):
        p = palette()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, False)
        w = self.width()
        if not self.rows:
            painter.setPen(QColor(p["muted"]))
            painter.drawText(self.rect(), Qt.AlignCenter, "Your ping to every server appears here after VALORANT "
                                                           "has started once.")
            return
        wide = w >= 680
        name_w = 150 if wide else 112
        value_w = 72
        typ_w = 118 if wide else 0
        bar_x = name_w + 10
        bar_room = max(60, w - bar_x - value_w - typ_w - 16)
        values = [r["now"] for r in self.rows if r["now"] is not None] + \
                 [r["typical"] for r in self.rows if r["typical"] is not None]
        scale = max(100.0, max(values) * 1.06) if values else 100.0
        caption = display_font("Caption")
        body = QFont(self.font())
        body.setPointSizeF(10.5)
        small = QFont(self.font())
        small.setPointSizeF(9.0)
        # header
        painter.setFont(caption)
        painter.setPen(QColor(p["faint"]))
        painter.drawText(QRectF(0, 0, name_w, self.HEAD - 6), Qt.AlignLeft | Qt.AlignVCenter, "SERVER")
        painter.drawText(QRectF(bar_x, 0, bar_room, self.HEAD - 6), Qt.AlignLeft | Qt.AlignVCenter, "PING NOW")
        painter.drawText(QRectF(bar_x + bar_room, 0, value_w, self.HEAD - 6), Qt.AlignRight | Qt.AlignVCenter, "MS")
        if typ_w:
            painter.drawText(QRectF(w - typ_w, 0, typ_w, self.HEAD - 6), Qt.AlignRight | Qt.AlignVCenter,
                             "TYPICAL · BEST")
        painter.setPen(QColor(p["border"]))
        painter.drawLine(0, self.HEAD - 3, w, self.HEAD - 3)
        best = next((r for r in self.rows if r["now"] is not None), None)
        self._hits = []
        for i, r in enumerate(self.rows):
            y = self.HEAD + i * self.ROW
            self._hits.append((QRectF(0, y, w, self.ROW), r))
            if i:
                painter.setPen(QColor(p["border"]))
                painter.drawLine(0, int(y), w, int(y))
            painter.setFont(body)
            painter.setPen(QColor(p["text"] if r["now"] is not None else p["faint"]))
            painter.drawText(QRectF(0, y, name_w, self.ROW), Qt.AlignLeft | Qt.AlignVCenter, r["city"])
            now = r["now"]
            if now is not None:
                color = p["text"] if r["preferred"] else p["success"] if r is best else p["muted"]
                bw = max(3.0, bar_room * min(now, scale) / scale)
                painter.fillRect(QRectF(bar_x, y + self.ROW / 2 - 5, bw, 10), QColor(color))
                if r["typical"] is not None:
                    tx = bar_x + bar_room * min(r["typical"], scale) / scale
                    painter.fillRect(QRectF(tx - 1, y + self.ROW / 2 - 9, 2, 18), QColor(p["faint"]))
                tag = "YOUR SERVER" if r["preferred"] else ("LOWEST" if r is best else "")
                if tag:
                    painter.setFont(caption)
                    painter.setPen(QColor(p["faint"]))
                    tag_rect = QRectF(bar_x + bw + 10, y, bar_room - bw - 10, self.ROW)
                    if tag_rect.width() > 70:
                        painter.drawText(tag_rect, Qt.AlignLeft | Qt.AlignVCenter, tag)
                painter.setFont(body)
                painter.setPen(QColor(p["text"]))
                painter.drawText(QRectF(bar_x + bar_room, y, value_w, self.ROW), Qt.AlignRight | Qt.AlignVCenter,
                                 f"{now} ms")
            else:
                painter.setFont(small)
                painter.setPen(QColor(p["faint"]))
                painter.drawText(QRectF(bar_x, y, bar_room + value_w, self.ROW), Qt.AlignLeft | Qt.AlignVCenter,
                                 "not measured at the last start")
            if typ_w and r["typical"] is not None:
                painter.setFont(small)
                painter.setPen(QColor(p["faint"]))
                painter.drawText(QRectF(w - typ_w, y, typ_w, self.ROW), Qt.AlignRight | Qt.AlignVCenter,
                                 f"{r['typical']:.0f} · {r['best']} ms")


class ServersTab(QWidget):
    def __init__(self, engine, gid, window):
        super().__init__()
        self.setObjectName("Transparent")
        self.engine, self.gid, self.window = engine, gid, window
        self.bridge = _Bridge()
        self.bridge.board.connect(self._on_board)
        self.bridge.status.connect(self._on_status)
        engine.ping_changed.connect(self._on_ping_changed)
        self._board = None
        self._status = None
        self._status_error = ""
        self._status_region = None
        self._status_at = 0.0
        self._status_busy = False
        self._loaded_at = 0.0
        self._demo = False
        self.busy = False

        self.btn_refresh = button("Refresh", "refresh", "Ghost", lambda: self.load(force=True),
                                  "Read VALORANT's newest measurements and ask Riot's status feed again")
        self.when_label = label("", "Faint", wrap=True)
        head = Reflow(breakpoint=700, spacing=12)
        head.add(vbox(label("Your ping to every VALORANT server", "H2"), self.when_label, spacing=4), 1)
        head.add(self.btn_refresh, 0, Qt.AlignTop)
        self.cards = {"server": StatCard("Your server"), "lowest": StatCard("Lowest ping"),
                      "steady": StatCard("Between game starts")}
        grid = ResponsiveGrid(min_width=190, max_cols=3, spacing=12)
        for card in self.cards.values():
            grid.add(card)
        self.board = PingBoard()
        self.legend = label("Bar: ping at the last game start · thin mark: typical over the last 14 days · "
                            "VALORANT measures once each time it starts, so press Refresh after playing.",
                            "Faint", wrap=True)
        board_card = Card(padding=18, spacing=12)
        board_card.add(head, grid, self.board, self.legend)

        self.insights_card = Card(padding=18, spacing=10)
        self.insights = vbox(spacing=10)
        self.insights_card.add(label("What this means", "H2"), self.insights)

        self.status_card = Card(padding=18, spacing=10)
        self.status_title = label("Riot server status", "H2")
        self.status_badge = Badge("", "info")
        self.status_badge.hide()
        self.btn_status = button("Open Riot's status page", "external", "Ghost", self._open_status)
        status_head = Reflow(breakpoint=640, spacing=12)
        status_head.add(hbox(self.status_title, self.status_badge, None, spacing=12), 1)
        status_head.add(self.btn_status, 0, Qt.AlignTop)
        self.status_box = vbox(spacing=10)
        self.status_card.add(status_head, self.status_box)

        self.setLayout(vbox(board_card, self.insights_card, self.status_card, spacing=16))
        self.render()
        self.render_status()

    # ---- loading (background: the game's logs are big) ----------------------

    def showEvent(self, event):
        super().showEvent(event)
        self.refresh()

    def refresh(self):
        """Called when the tab is shown or the page refreshes: re-read the logs when they may have changed."""
        if not self._demo and time.monotonic() - self._loaded_at > STALE_SECONDS:
            self.load()

    def _on_ping_changed(self):
        self._loaded_at = 0.0
        if self.isVisible():
            self.load()

    def load(self, force=False):
        if self.busy or self._demo:
            return
        self.busy = True
        self.btn_refresh.setEnabled(False)
        if force:
            self._status_at = 0.0

        def work():
            try:
                from ..games.valorant import LOG_DIR
                b = ping.board(ping.update(LOG_DIR))
            except Exception:
                log.exception("Reading the ping measurements failed")
                try:
                    b = ping.board(ping.load())
                except Exception:
                    b = None
            self.bridge.board.emit(b)

        threading.Thread(target=work, name="ping-board", daemon=True).start()

    def _on_board(self, b):
        try:
            self.busy = False
            if self._demo:
                return                              # example data stays (screenshots, tests)
            self._loaded_at = time.monotonic()
            self.btn_refresh.setEnabled(True)
            self._board = b
            self.render()
            region = b["region"] if b else None
            if region and (region != self._status_region or time.monotonic() - self._status_at > STATUS_SECONDS):
                self._load_status(region)
            else:
                self.render_status()
        except RuntimeError:
            pass                                    # the page was rebuilt (theme change) while the thread ran

    def _load_status(self, region):
        if self._status_busy:
            return
        self._status_busy = True
        self.render_status()

        def work():
            try:
                st, err = ping.fetch_status(region), ""
            except Exception as exc:                # no network, feed changed, ...: shown as "couldn't check"
                log.warning("Riot status feed (%s): %s", region, exc)
                st, err = None, str(exc) or exc.__class__.__name__
            self.bridge.status.emit(st, err)

        threading.Thread(target=work, name="riot-status", daemon=True).start()

    def _on_status(self, st, err):
        try:
            self._status_busy = False
            self._status_at = time.monotonic()
            self._status, self._status_error = st, err
            if st:
                self._status_region = st["region"]
            self.render_status()
        except RuntimeError:
            pass

    def set_demo(self, samples, status=None, now=None):
        """Example data for screenshots and tests: no logs read, no network."""
        self._demo = True
        self._board = ping.board(samples, now=now)
        self._status = status
        self._status_region = status["region"] if status else None
        self._loaded_at = time.monotonic()
        self.render()
        self.render_status()

    def _open_status(self):
        QDesktopServices.openUrl(QUrl(ping.status_page(self._board["region"] if self._board else None)))

    # ---- rendering ----------------------------------------------------------

    def render(self):
        b = self._board
        installed = self.engine.info[self.gid].installed
        if not b:
            self.when_label.setText("VALORANT measures its ping to every server of your region each time it starts. "
                                    + ("Play once and this board fills in by itself."
                                       if installed else "Install VALORANT, play once, and this board fills in by itself."))
            for card in self.cards.values():
                card.set("–", "")
            self.cards["server"].set("–", "waiting for the first game start")
        else:
            when = b["when"]
            n = b["recent"]
            self.when_label.setText(
                f"Measured by VALORANT itself when it starts — last on {when:%d %b, %H:%M}" if when else
                "Measured by VALORANT itself when it starts")
            self.when_label.setText(self.when_label.text() + f" · {b['region_name']} · {n} measurement"
                                                             f"{'s' if n != 1 else ''} in the last {b['days']} days")
            pref = b["preferred"][0] if b["preferred"] else None
            best = b["best"]
            if pref and pref["now"] is not None:
                self.cards["server"].set(f"{pref['now']} ms", f"{pref['city']} · VALORANT's pick · "
                                                               f"{ping.quality(pref['now'])}")
            else:
                self.cards["server"].set("–", "VALORANT hasn't named a preferred server")
            if best:
                self.cards["lowest"].set(f"{best['now']} ms", best["city"] + (" · the same server" if pref and
                                                                              best["pod"] == pref["pod"] else ""))
            else:
                self.cards["lowest"].set("–", "")
            if b["spread"]:
                lo, hi = b["spread"]
                steady = hi - lo <= ping.STEADY_MS
                self.cards["steady"].set(f"{lo}–{hi} ms" if lo != hi else f"{lo} ms",
                                         f"{'steady' if steady else 'unsteady'} · {b['focus']['city']} over "
                                         f"{b['sessions']} game starts")
            else:
                self.cards["steady"].set("–", "known after 3 game starts")
        self.board.set_board(b)
        self.board.setVisible(bool(b))
        self.legend.setVisible(bool(b))
        p = palette()
        clear_layout(self.insights)
        for name, key, text in ping.insights(b):
            ic = QLabel()
            ic.setPixmap(icons.pixmap(name, p[key], 18))
            ic.setAlignment(Qt.AlignTop)
            row = hbox(ic, spacing=12)
            row.addWidget(label(text, "Muted", wrap=True), 1)
            self.insights.addLayout(row)

    def _status_line(self, text, name="Muted"):
        self.status_box.addWidget(label(text, name, wrap=True))

    def render_status(self):
        clear_layout(self.status_box)
        st, b = self._status, self._board
        if st is None:
            self.status_title.setText("Riot server status")
            self.status_badge.hide()
            if not b:
                self._status_line("Riot's notices for your region appear here once VALORANT has started once "
                                  "(that's how TrueStretch learns your region).")
            elif self._status_busy or not self._status_error:
                self._status_line("Checking Riot's status feed…")
            else:
                self.status_badge.set("Couldn't check", "warning")
                self.status_badge.show()
                self._status_line("Riot's status feed couldn't be read right now (no internet, or the feed is down). "
                                  "The status page has the same information.")
            return
        self.status_title.setText(f"Riot server status — {st['name']}")
        entries, older = st["entries"], st["older"]
        self.status_badge.show()
        tail = f" · checked {st['checked']:%H:%M}"
        if older:
            tail = f" · {len(older)} older notice{'s' if len(older) != 1 else ''} still on Riot's page" + tail
        if not entries:
            self.status_badge.set("All good", "success")
            self._status_line("No problems or maintenance reported for VALORANT on Windows right now" + tail)
            return
        severities = [e["severity"] for e in entries]
        kind = "danger" if "critical" in severities else "warning" if any(s in ("warning", "in_progress", "scheduled")
                                                                            for s in severities) else "info"
        self.status_badge.set(f"{len(entries)} notice{'s' if len(entries) != 1 else ''}", kind)
        p = palette()
        for e in entries[:4]:
            ic = QLabel()
            ic.setPixmap(icons.pixmap("alert" if e["kind"] == "incident" else "clock",
                                      p["danger" if e["severity"] == "critical" else "warning"], 18))
            ic.setAlignment(Qt.AlignTop)
            text = vbox(spacing=2)
            when = f" · {e['updated']:%d %b, %H:%M}" if e["updated"] else ""
            text.addWidget(label(e["title"], None))
            text.addWidget(label(f"{e['kind'].capitalize()}{' · ' + e['severity'] if e['severity'] else ''}{when}",
                                 "Faint"))
            if e["text"]:
                text.addWidget(label(e["text"], "Muted", wrap=True))
            row = hbox(ic, spacing=12)
            row.addLayout(text, 1)
            self.status_box.addLayout(row)
        self._status_line("From Riot's public status feed" + tail, "Faint")
