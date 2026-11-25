"""Main window: top bar (navigation + PLAY), pages, footer, tray icon, and the play / restore flows."""

import ctypes
import threading
from ctypes import wintypes
from datetime import datetime

from PySide6.QtCore import QEvent, QObject, QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap, QPolygonF
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (QApplication, QButtonGroup, QDialog, QFrame, QLabel, QMainWindow, QMenu,
                               QMessageBox, QPushButton, QStackedWidget, QSystemTrayIcon, QTabBar, QWidget)

from .. import APP_NAME, VERSION, display
from ..engine import MonitorDriversOn, StretchError
from ..paths import log, resource_path
from ..readcache import reads
from ..system import set_dark_title_bar
from . import icons, theme
from .game_page import GamePage
from .matches_page import MatchesPage
from .mypc_page import MyPcPage
from .optimize_page import OptimizePage
from .pages import AboutPage, BackupsPage, SettingsPage
from .welcome import WelcomeDialog
from .widgets import Badge, FocusRing, TacticalButton, Toast, button, game_pixmap, hbox, label, vbox

LOGO = resource_path("assets/logo.svg")


class _Background(QObject):
    """Carries a worker thread's result back to the UI thread."""
    done = Signal(object, object)       # result, exception


class _WindowRef:
    """What a background fix gets instead of the window: the native handle, read on the UI thread beforehand
    (UAC prompts are parented to it), and nothing else - widgets must not be touched from a worker thread."""

    def __init__(self, hwnd):
        self._hwnd = hwnd

    def winId(self):
        return self._hwnd
WM_HOTKEY = 0x0312
HOTKEY_ID = 0x5453
MOD_ALT, MOD_CONTROL, MOD_NOREPEAT = 0x1, 0x2, 0x4000


def render_logo(size, dpr=2.0):
    pm = QPixmap(int(size * dpr), int(size * dpr))
    pm.fill(Qt.transparent)
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.Antialiasing)
    QSvgRenderer(str(LOGO)).render(painter, QRectF(0, 0, size * dpr, size * dpr))
    painter.end()
    pm.setDevicePixelRatio(dpr)
    return pm


def app_icon():
    ic = QIcon()
    for s in (16, 20, 24, 32, 48, 64, 128, 256):
        ic.addPixmap(render_logo(s, 1.0))
    return ic


class ConfirmResolutionDialog(QDialog):
    """'Keep this resolution?' with a countdown, so a blank screen fixes itself."""

    def __init__(self, parent, mode, seconds, test=False):
        super().__init__(parent)
        self.setWindowTitle(APP_NAME)
        self.setWindowFlag(Qt.WindowStaysOnTopHint)
        self.setWindowFlag(Qt.WindowContextHelpButtonHint, False)
        self.setModal(True)
        self.setMinimumWidth(560)
        self.remaining = seconds
        p = theme.palette()
        ic = QLabel()
        ic.setPixmap(icons.pixmap("monitor", p["accent"], 30))
        self.countdown = label("", "Muted")
        if test:
            title = "Does your whole screen look stretched?"
            text = (f"Your desktop is now {mode}. Look at the edges of your monitor: the picture should fill it "
                    "completely and look wider than normal (round icons become ovals). Black bars at the left and "
                    "right mean the graphics scaling isn't Full-screen yet.")
            no, yes = "Black bars / not stretched", "Yes, it fills the screen"
        else:
            title, text = "Keep this resolution?", f"Your desktop is now {mode}. If everything looks right, keep it."
            no, yes = "Switch back", "Keep it"
        revert = button(no, "undo", None, self.reject)
        keep = button(yes, "check", "Primary", self.accept)
        self.timed_out = False
        (keep if test else revert).setDefault(True)     # a test: Enter means "it fills"; a real change: switch back
        self.setLayout(vbox(
            hbox(ic, vbox(label(title, "H2"), label(text, "Muted", wrap=True), spacing=4), spacing=16),
            self.countdown,
            hbox(None, revert, keep, spacing=8),
            spacing=18, margins=(24, 22, 24, 20)))
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(1000)
        self._tick(first=True)

    def _tick(self, first=False):
        if not first:
            self.remaining -= 1
        if self.remaining <= 0:
            self.timed_out = True
            self.reject()
            return
        self.countdown.setText(f"Switching back automatically in {self.remaining} s…")


class Backdrop(QWidget):
    """The window background: deep navy with a few thin diagonal lines and a faint oversized chevron - the kind of
    quiet geometric detail tactical game menus use behind their panels."""

    def paintEvent(self, _event):
        p = theme.palette()
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(p["bg"]))
        if not p["dark"]:
            return
        painter.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        line = QColor(p["text"])
        line.setAlpha(9)
        painter.setPen(QPen(line, 1))
        for i in range(5):
            x = w * 0.62 + i * 46
            painter.drawLine(int(x), h, int(x + h * 0.55), 0)
        chevron = QColor(p["accent"])
        chevron.setAlpha(10)
        painter.setPen(Qt.NoPen)
        painter.setBrush(chevron)
        cx, cy, s = w * 0.86, h * 0.62, min(w, h) * 0.32
        painter.drawPolygon(QPolygonF([QPointF(cx - s, cy - s), QPointF(cx, cy), QPointF(cx - s, cy + s),
                                       QPointF(cx - s * 0.72, cy + s), QPointF(cx + s * 0.28, cy),
                                       QPointF(cx - s * 0.72, cy - s)]))


class SettingsShell(QWidget):
    """SETTINGS: app settings, backups and about in one place."""

    def __init__(self, engine, window):
        super().__init__()
        self.setObjectName("Transparent")
        # A bare tab bar centred over a stack (QTabWidget's document mode ignored the centre alignment and left the
        # tabs hugging the window edge while the pages below are a centred column).
        self.tabs = QTabBar()
        self.tabs.setDocumentMode(True)
        self.tabs.setExpanding(False)
        self.tabs.setDrawBase(False)
        self.tabs.setFont(theme.button_font(11, spacing=2.0))
        self.tabs.setCursor(Qt.PointingHandCursor)
        self.stack = QStackedWidget()
        self.general = SettingsPage(engine, window)
        self.backups = BackupsPage(engine, window)
        self.about = AboutPage(engine, window)
        for page, name in ((self.general, "General"), (self.backups, "Backups"), (self.about, "About")):
            self.tabs.addTab(name)
            self.stack.addWidget(page)
        self.tabs.currentChanged.connect(self._tab_changed)
        layout = vbox(hbox(None, self.tabs, None, spacing=0), self.stack, spacing=0, margins=(0, 10, 0, 0))
        self.setLayout(layout)

    def _tab_changed(self, index):
        self.stack.setCurrentIndex(index)
        self.refresh()

    def show_tab(self, name):
        self.tabs.setCurrentIndex({"general": 0, "backups": 1, "about": 2}.get(name, 0))

    def refresh(self):
        self.stack.currentWidget().refresh()

    def settle(self):
        self.stack.currentWidget().settle()


class MainWindow(QMainWindow):
    NAV = [("game:valorant", "VALORANT", None), ("optimize", "Optimize", "wand"), ("matches", "Matches", "chart"),
           ("mypc", "My PC", "pulse"), ("settings", "Settings", "settings")]

    def __init__(self, engine):
        super().__init__()
        self.engine = engine
        self._quitting = False
        self._tray_hint_shown = False
        self._current = None
        self._busy = None               # caption of the background step running right now (see run_background)
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(app_icon())
        self.setMinimumSize(900, 600)
        self._fit_to_screen(1240, 820)

        self._focus_ring = FocusRing(self)
        QApplication.instance().installEventFilter(self._focus_ring)
        central = Backdrop()
        central.setObjectName("Content")
        self.setCentralWidget(central)
        self.stack = QStackedWidget()
        self.topbar = self._build_topbar()
        self.footer = self._build_footer()
        from .update import UpdateBar, UpdateController
        self.update_bar = UpdateBar(self.open_update)
        self.updates = UpdateController(engine.settings, self)
        self.updates.available.connect(self._update_available)
        self.updates.result.connect(lambda level, text: engine.notify(level, text))
        self._update_holder = QWidget()
        self._update_holder.setObjectName("Transparent")
        self._update_holder.setLayout(vbox(self.update_bar, margins=(24, 14, 24, 0)))
        self._update_holder.hide()
        central.setLayout(vbox(self.topbar, self._update_holder, self.stack, self.footer, spacing=0))
        self.toast = Toast(central)

        self.pages = {}
        self.gid = next(iter(engine.games))
        with reads():                   # one display query serves every page built here, not 33
            self._build_pages()
            self.navigate(f"game:{self.gid}")

            self._build_tray()
            self._register_hotkey()
            engine.changed.connect(self.refresh_all)
            engine.message.connect(self.on_message)
            self.footer_timer = QTimer(self)
            self.footer_timer.timeout.connect(self._refresh_footer)
            self.footer_timer.start(3000)
            self.refresh_all()

    # ---- layout -----------------------------------------------------------

    def logo_pixmap(self, size):
        return render_logo(size)

    def _build_topbar(self):
        bar = QFrame()
        bar.setObjectName("TopBar")
        bar.setFixedHeight(66)
        logo = QLabel()
        logo.setPixmap(render_logo(30))
        self.wordmark = label(APP_NAME, "Brand")
        brand = hbox(logo, self.wordmark, spacing=10)
        self.nav_group = QButtonGroup(self)
        self.nav_buttons = {}
        nav = hbox(spacing=2)
        for key, text, icon_name in self.NAV:
            nav.addWidget(self._nav(key, text, icon_name))
        self.play_btn = TacticalButton("Play stretched")
        self.play_btn.setFont(theme.button_font(12, spacing=2.4))
        self.play_btn.setMinimumWidth(230)
        self.play_btn.setCursor(Qt.PointingHandCursor)
        self.play_btn.clicked.connect(lambda: self.play(self.gid))
        self.top_status = Badge("", "info")
        self.top_status.setFont(theme.button_font(9, spacing=1.6))
        layout = hbox(brand, 18, nav, None, self.play_btn, None, self.top_status, spacing=10,
                      margins=(18, 0, 18, 0))
        bar.setLayout(layout)
        return bar

    def _nav(self, key, text, icon_name):
        b = QPushButton(text)
        b.setObjectName("TopNav")
        b.setFont(theme.button_font(12, spacing=2.0))
        b.setCheckable(True)
        b.setCursor(Qt.PointingHandCursor)
        b.setIconSize(QSize(16, 16))
        b.setProperty("icon_name", icon_name)
        b.setProperty("full_text", text)
        b.clicked.connect(lambda: self.navigate(key))
        self.nav_group.addButton(b)
        self.nav_buttons[key] = b
        return b

    def _paint_nav_icons(self):
        p = theme.palette()
        for key, b in self.nav_buttons.items():
            name = b.property("icon_name")
            if name:
                b.setIcon(icons.icon(name, p["muted"], 16, active_color=p["text"]))
            elif key.startswith("game:"):
                gid = key.split(":", 1)[1]
                b.setIcon(QIcon(game_pixmap(self.engine.games[gid], self.engine.info.get(gid), 16)))

    def _build_footer(self):
        bar = QFrame()
        bar.setObjectName("Footer")
        bar.setFixedHeight(32)
        self.footer_desktop = QLabel()
        self.footer_game = QLabel()
        self.footer_state = QLabel()
        self.footer_version = QLabel(f"V{VERSION}")
        bar.setLayout(hbox(self.footer_desktop, None, self.footer_state, self.footer_version,
                           spacing=26, margins=(20, 0, 20, 0)))
        return bar

    def _add_page(self, key, page):
        self.pages[key] = page
        self.stack.addWidget(page)

    def navigate(self, key):
        aliases = {"home": f"game:{self.gid}", "backups": "settings", "about": "settings"}
        target = aliases.get(key, key)
        page = self.pages.get(target)
        if not page:
            return
        self.nav_buttons[target].setChecked(True)
        self.stack.setCurrentWidget(page)
        self._current = target
        if key in ("backups", "about"):
            page.show_tab(key)
        self._refresh_page(page)
        if target.startswith("game:"):
            self.engine.settings.app["last_game"] = target.split(":", 1)[1]

    def show_game(self, gid, tab=None):
        self.navigate(f"game:{gid}")
        if tab:
            self.pages[f"game:{gid}"].show_tab(tab)

    # ---- refresh / theme --------------------------------------------------

    def refresh_all(self):
        """Only the page on screen is redrawn; the others refresh when they're opened (keeps the app snappy)."""
        with reads():
            self._paint_nav_icons()
            page = self.pages.get(self._current)
            if page is not None and self.isVisible() and not self.isMinimized():   # hidden: refreshed when shown
                self._refresh_page(page)
            self._refresh_top()
            self._refresh_footer()
            self._refresh_tray()

    def _refresh_page(self, page):
        try:
            with reads():               # the display is asked once per refresh, however many widgets ask
                page.refresh()
                page.settle()
        except Exception:
            log.exception("Refreshing %s failed", type(page).__name__)

    # ---- background steps -------------------------------------------------

    def run_background(self, caption, work, done):
        """Runs work() in a worker thread so the window keeps drawing (administrator prompts, pnputil and driver
        calls take seconds; before 2.2.0 the window froze for up to a minute). The PLAY button shows `caption`
        meanwhile. done(result, error) runs on the UI thread afterwards; error is the exception work() raised."""
        if self._busy:
            self.engine.notify("info", f"Still busy: {self._busy.lower()}…")
            return False
        self._busy = caption
        self._refresh_top()
        bridge = _Background(self)

        def finish(result, error):
            self._busy = None
            bridge.deleteLater()
            try:
                done(result, error)
            finally:
                self.refresh_all()

        bridge.done.connect(finish, Qt.QueuedConnection)

        def run():
            try:
                bridge.done.emit(work(), None)
            except Exception as exc:    # every error reaches the UI thread; none dies silently in the worker
                bridge.done.emit(None, exc)

        threading.Thread(target=run, name="background-step", daemon=True).start()
        return True

    def _refresh_top(self):
        e, gid = self.engine, self.gid
        running = e.running.get(gid)
        if self._busy:
            text, kind = self._busy.upper() + "…", "info"
            self.play_btn.setText("Working…")
            self.play_btn.setEnabled(False)
            self.play_btn.setToolTip(self._busy + "…")
        elif running:
            state = e.match_state(gid)
            text, kind = (("IN MATCH · STRETCHED", "accent") if e.is_stretched(gid) else
                          ("IN MATCH", "warning") if state == "in match" else ("MENU · NATIVE", "success"))
            self.play_btn.setText("In game" if getattr(self, "_compact", False) else "VALORANT running")
            self.play_btn.setEnabled(False)
        elif e.is_launching(gid):
            # Starting: say so on the button and don't let a second click launch the game twice.
            text, kind = "WAITING FOR VALORANT", "info"
            self.play_btn.setText("Starting…")
            self.play_btn.setEnabled(False)
        elif not e.info.get(gid) or not e.info[gid].installed:
            text, kind = "VALORANT NOT FOUND", "danger"
            self.play_btn.setText("Play" if getattr(self, "_compact", False) else "Play stretched")
            self.play_btn.setEnabled(False)
            self.play_btn.setToolTip("VALORANT wasn't found on this PC. Install it, then press Rescan.")
        else:
            text, kind = "", "success"
            self.play_btn.setText("Play" if getattr(self, "_compact", False) else "Play stretched")
            self.play_btn.setEnabled(True)
            self.play_btn.setToolTip("Sets everything up and starts VALORANT; the desktop stretches once a match "
                                     "has loaded")
        self.top_status.set(text, kind)
        self.top_status.setVisible(bool(text) and not getattr(self, "_compact", False))
        self.play_btn.updateGeometry()

    def _refresh_footer(self):
        p = theme.palette()
        current = display.current_mode()
        dot = lambda color: f'<span style="color:{color}">■</span>'
        self.footer_desktop.setText(f"{dot(p['info'])}&nbsp; DESKTOP {current}" if current else "")
        st = self.engine.state
        self.footer_state.setText(f"{dot(p['accent'])}&nbsp; STRETCHED" if st.stretched
                                  else f"{dot(p['faint'])}&nbsp; NATIVE")
        self._refresh_top()

    def apply_theme(self):
        before = theme.palette()
        theme.set_theme(self.engine.settings.app["theme"])
        QApplication.instance().setStyleSheet(theme.stylesheet())
        set_dark_title_bar(int(self.winId()), theme.palette()["dark"])
        self.centralWidget().update()
        if theme.palette() is not before and self.pages:
            # Icons are drawn in the theme's colours when a page is built: rebuild the pages so a theme switch
            # takes full effect right away instead of after a restart. Later, so the click that asked for it
            # finishes first.
            QTimer.singleShot(0, self._rebuild_pages)
        self.refresh_all()

    def _build_pages(self):
        for gid in self.engine.games:
            self._add_page(f"game:{gid}", GamePage(self.engine, self, gid))
        self._add_page("optimize", OptimizePage(self.engine, self))
        self._add_page("matches", MatchesPage(self.engine, self))
        self._add_page("mypc", MyPcPage(self.engine, self, self.gid))
        self._add_page("settings", SettingsShell(self.engine, self))

    def _rebuild_pages(self):
        current = self._current
        settings_tab = self.pages["settings"].tabs.currentIndex() if "settings" in self.pages else 0
        for page in list(self.pages.values()):
            self.stack.removeWidget(page)
            page.deleteLater()
        self.pages = {}
        self._build_pages()
        self.navigate(current or f"game:{self.gid}")
        self.pages["settings"].tabs.setCurrentIndex(settings_tab)

    def showEvent(self, event):
        super().showEvent(event)
        set_dark_title_bar(int(self.winId()), theme.palette()["dark"])
        QTimer.singleShot(0, self.refresh_all)

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.WindowStateChange and not self.isMinimized() and self.isVisible():
            QTimer.singleShot(0, self.refresh_all)

    def _fit_to_screen(self, w, h):
        """Open at the preferred size, but never bigger than the screen (a 1366x768 laptop or a 1080p screen at 150%
        scaling has less room than 1240x820), centred."""
        screen = QApplication.primaryScreen()
        if not screen:
            self.resize(w, h)
            return
        area = screen.availableGeometry()
        w, h = min(w, int(area.width() * 0.92)), min(h, int(area.height() * 0.9))
        self.resize(max(w, 900), max(h, 600))
        self.move(area.x() + (area.width() - self.width()) // 2, area.y() + (area.height() - self.height()) // 2)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.toast.reposition()
        w = event.size().width()
        self.wordmark.setVisible(w >= 1180)

        self._compact = w < 1040
        self.play_btn.setMinimumWidth(150 if self._compact else 230)
        self._refresh_top()
        # Narrow window: every tab keeps its label, just set tighter (the old rule left "VALORANT" in words and the
        # other four as bare icons - inconsistent, and a new player had to guess what the icons were).
        tight = w < 1000
        if tight != getattr(self, "_tight_nav", None):
            self._tight_nav = tight
            font = theme.button_font(10.5 if tight else 12, spacing=1.2 if tight else 2.0)
            for b in self.nav_buttons.values():
                b.setFont(font)
                b.setProperty("tight", "true" if tight else "false")
                b.style().unpolish(b)
                b.style().polish(b)
                b.updateGeometry()          # a button doesn't re-measure itself after a font change: labels clipped
        for b in self.nav_buttons.values():
            b.setText(b.property("full_text"))
            b.setToolTip(b.property("full_text"))

    # ---- messages ---------------------------------------------------------

    def on_message(self, level, text):
        if self.isVisible() and not self.isMinimized():
            self.toast.show_message(level, text)
        elif self.tray and self.engine.settings.app["notifications"] and level != "info":
            kind = {"error": QSystemTrayIcon.Critical, "warning": QSystemTrayIcon.Warning}.get(
                level, QSystemTrayIcon.Information)
            self.tray.showMessage(APP_NAME, text, kind, 4000)

    def _error(self, text):
        log.error(text)                      # a message box only (it used to show a toast with the same text too)
        self.engine.history.append((datetime.now(), "error", text))
        box = QMessageBox(self)
        box.setWindowTitle(APP_NAME)
        box.setIcon(QMessageBox.Warning)
        box.setText(text)
        box.exec()

    # ---- flows ------------------------------------------------------------

    def play(self, gid, launch=True):
        game = self.engine.games[gid]
        if self.engine.running.get(gid):
            current = game.current_settings(self.engine.info[gid]) if hasattr(game, "current_settings") else None
            if current and current.get("ready"):
                self.engine.notify("info", f"{game.name} is already running and set up — it stretches as soon as "
                                           "a match loads.")
            else:
                self._error(f"{game.name} is already running. Close it, then press Play stretched again.")
            return
        try:
            self.engine.prepare(gid)
        except MonitorDriversOn:
            # Play stretched = consent. Windows shows its own administrator prompt; nothing else to answer.
            # pnputil runs in the background so the window keeps drawing; Play continues once it's done.
            self.engine.notify("info", "Turning the monitor drivers off (Windows asks for permission once)…")
            hwnd = int(self.winId())

            def done(_result, error):
                if error is not None:
                    self._error(str(error) if isinstance(error, StretchError)
                                else f"Couldn't change the monitor drivers: {error}")
                elif self.engine.monitor_drivers_on(gid):
                    self._error("Some monitor drivers are still on. Restart your PC, then press Play stretched.")
                else:
                    self.play(gid, launch)

            self.run_background("Turning monitor drivers off",
                                lambda: self.engine.set_monitor_drivers(False, hwnd), done)
            return
        except StretchError as exc:
            self._error(str(exc))
            return
        if launch:
            try:
                self.engine.launch(gid)
            except StretchError as exc:
                self._error(str(exc))

    def test_stretch(self, gid):
        """Stretch the desktop for a few seconds so the player can SEE whether the screen fills edge to edge."""
        if self.engine.running.get(gid):
            self._error("Close VALORANT first — during a match TrueStretch switches by itself (or press Ctrl+Alt+S).")
            return
        try:
            result = self.engine.stretch_now(gid, "test")
        except StretchError as exc:
            self._error(str(exc))
            return
        dialog = ConfirmResolutionDialog(self if self.isVisible() else None, result.mode,
                                         self.engine.settings.app["confirm_seconds"], test=True)
        kept = dialog.exec() == QDialog.Accepted
        self.engine.revert_display("test finished")
        if kept:
            self.engine.notify("success", "Your screen stretches correctly — you're ready to play.")
        elif dialog.timed_out:
            self.engine.notify("info", "Test ended — your normal resolution is back. Press Test stretch any time.")
        else:
            self.engine.repair_scaling(gid)
            page = self.pages.get(f"game:{gid}")
            if page is not None:
                page.troubleshoot("TrueStretch has just set the stretch scaling in your graphics driver and Windows "
                                  "again. Press Test stretch once more — and if it still isn't right, find what you "
                                  "see below.")

    def restore(self, gid):
        game = self.engine.games[gid]
        if not self._ask(f"Put back {game.name}'s original settings?",
                         f"Your {game.name} settings files go back to how they were before TrueStretch, and your "
                         "desktop to its normal resolution.", "Restore normal"):
            return
        try:
            self.engine.restore(gid)
        except StretchError as exc:
            self._error(str(exc))

    def run_fix(self, item):
        """Runs a My PC fix after the click finishes (the page is rebuilt afterwards)."""
        QTimer.singleShot(0, lambda: self._run_fix(item))

    def _run_fix(self, item):
        if getattr(item, "background", None):
            ref = _WindowRef(int(self.winId()))

            def done(_result, error):
                if error is not None:
                    self._error(str(error) if isinstance(error, (StretchError, OSError, display.DisplayError))
                                else f"{item.fix_label} failed: {error}")

            self.run_background(item.background, lambda: item.fix(ref), done)
            return
        try:
            undo = item.fix(self)
        except (StretchError, OSError, display.DisplayError) as exc:
            self._error(str(exc))
            return
        if callable(undo):
            app = self.engine.settings.app
            current = display.current_mode(self.engine.display_for(next(iter(self.engine.games))).device)
            if app["confirm_display_change"]:
                dialog = ConfirmResolutionDialog(self, current, app["confirm_seconds"])
                if dialog.exec() != QDialog.Accepted:
                    try:
                        undo()
                        self.engine.notify("info", "Switched back.")
                    except (OSError, display.DisplayError) as exc:
                        self._error(str(exc))
        self.engine.changed.emit()

    def startup(self):
        """First launch: welcome tour. Every launch: offer to undo a stretch left over from a crash."""
        if not self.engine.settings.app.get("onboarded"):
            self.show_welcome()
        self.check_recovery()
        if not self.hotkey_ok:
            self.engine.notify("warning", "Another program already uses TrueStretch's hotkeys (Ctrl+Alt+S, "
                                          "Ctrl+Alt+↑/↓). Stretching in matches still works automatically — close "
                                          "that program and restart TrueStretch to get the hotkeys back.")

    # ---- updates ----------------------------------------------------------

    def _update_available(self, release):
        self.update_bar.show_release(release)
        self._update_holder.show()
        if self.tray and (not self.isVisible() or self.isMinimized()):
            self.tray.showMessage(APP_NAME, f"Version {release.version} is available — open TrueStretch to update.",
                                  QSystemTrayIcon.Information, 5000)
        self.refresh_all()

    def open_update(self):
        release = self.updates.release
        if release is None:
            self.updates.check(manual=True)
            return
        if any(self.engine.running.values()):
            self._error("Close VALORANT first, then update — TrueStretch is switching your resolution while you play.")
            return
        from .update import UpdateDialog
        UpdateDialog(release, self).exec()

    def show_welcome(self):
        if not self.isVisible():
            self.bring_to_front()
        WelcomeDialog(self.engine, self).exec()
        self.engine.settings.app["onboarded"] = True
        self.engine.save()

    def check_recovery(self):
        if not self.engine.needs_recovery():
            return
        mode = display.Mode.from_list(self.engine.state.data.get("mode"))
        if self._ask("Your desktop is still stretched", f"It's still at {mode} from last time — TrueStretch or the "
                     "game closed unexpectedly.", "Switch back now", "Keep it stretched"):
            self.engine.revert_display("recovered")

    def _ask(self, title, text, yes, no="Cancel"):
        """A question with real verbs on the buttons instead of Yes / No."""
        box = QMessageBox(self if self.isVisible() else None)
        box.setWindowTitle(APP_NAME)
        box.setIcon(QMessageBox.Question)
        box.setText(title)
        box.setInformativeText(text)
        ok = box.addButton(yes, QMessageBox.AcceptRole)
        box.addButton(no, QMessageBox.RejectRole)
        box.setDefaultButton(ok)
        box.exec()
        return box.clickedButton() is ok

    # ---- tray & closing ---------------------------------------------------

    def _build_tray(self):
        self.tray = None
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        self.tray = QSystemTrayIcon(app_icon(), self)
        self.tray.setToolTip(APP_NAME)
        menu = QMenu()
        self.tray_actions = {}
        for gid, game in self.engine.games.items():
            self.tray_actions[gid] = menu.addAction(f"Play {game.name} stretched", lambda g=gid: self.play(g))
        self.tray_revert = menu.addAction("Back to normal resolution", lambda: self.engine.revert_display("tray"))
        menu.addSeparator()
        menu.addAction(f"Open {APP_NAME}", self.bring_to_front)
        menu.addAction("Quit", self.quit)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(
            lambda reason: self.bring_to_front() if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick)
            else None)
        self.tray.show()

    def _refresh_tray(self):
        if not self.tray:
            return
        for gid, action in self.tray_actions.items():
            action.setEnabled(not self.engine.running.get(gid))
        self.tray_revert.setEnabled(self.engine.state.stretched)
        self.tray.setToolTip(f"{APP_NAME} — stretched mode {'on' if self.engine.state.stretched else 'off'}")

    # ---- global hotkey (works while the game has focus) --------------------

    def _register_hotkey(self):
        mods = MOD_CONTROL | MOD_ALT | MOD_NOREPEAT
        hwnd = int(self.winId())
        self.hotkey_ok = True
        for offset, key, name in ((0, ord("S"), "Ctrl+Alt+S"), (1, 0x26, "Ctrl+Alt+Up"), (2, 0x28, "Ctrl+Alt+Down")):
            if not ctypes.windll.user32.RegisterHotKey(hwnd, HOTKEY_ID + offset, mods, key):
                self.hotkey_ok = False
                log.warning("%s is used by another program; that hotkey isn't available", name)

    def nativeEvent(self, event_type, message):
        if bytes(event_type) == b"windows_generic_MSG":
            msg = wintypes.MSG.from_address(int(message))
            if msg.message == WM_HOTKEY and HOTKEY_ID <= msg.wParam <= HOTKEY_ID + 2:
                QTimer.singleShot(0, lambda which=msg.wParam - HOTKEY_ID: self._on_hotkey(which))
                return True, 0
        return super().nativeEvent(event_type, message)

    def _on_hotkey(self, which=0):
        gid = next(iter(self.engine.games))
        try:
            if which == 0:
                self.engine.toggle_stretch(gid)
            else:
                self.engine.step_stretch(gid, +1 if which == 1 else -1)
        except StretchError as exc:
            self.engine.notify("error", str(exc))

    def bring_to_front(self):
        self.show()
        self.setWindowState((self.windowState() & ~Qt.WindowMinimized) | Qt.WindowActive)
        self.raise_()
        self.activateWindow()

    def quit(self):
        self._quitting = True
        self.close()

    def closeEvent(self, event):
        if not self._quitting and self.tray and self.engine.settings.app["close_to_tray"]:
            event.ignore()
            self.hide()
            if not self._tray_hint_shown:
                self._tray_hint_shown = True
                self.tray.showMessage(APP_NAME, "Still running in the tray, so it can switch your resolution back "
                                      "after you play.", QSystemTrayIcon.Information, 3500)
            return
        self.engine.settings.save()
        self.engine.shutdown()
        if self.tray:
            self.tray.hide()
        event.accept()
        QApplication.instance().quit()
