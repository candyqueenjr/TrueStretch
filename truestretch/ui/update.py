"""Update UI: background check, the 'new version' bar, and the download-and-restart dialog."""

import threading

from PySide6.QtCore import QObject, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QApplication, QDialog, QProgressBar, QTextBrowser

from .. import APP_NAME, VERSION, updater
from ..paths import log
from .widgets import Card, button, hbox, label, vbox

CHECK_EVERY_MS = 6 * 60 * 60 * 1000


class UpdateController(QObject):
    """Checks GitHub in a background thread; never blocks or bothers the player when offline."""
    available = Signal(object)          # updater.Release
    result = Signal(str, str)           # level, text - only for checks the player started

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.release = None
        self._busy = False
        self.timer = QTimer(self)
        self.timer.timeout.connect(lambda: self.check(manual=False))
        self.timer.start(CHECK_EVERY_MS)
        self._done.connect(self._finished)

    _done = Signal(object, object, bool)  # release or None, error or None, manual

    def start(self):
        if self.settings.app.get("auto_update", True):
            QTimer.singleShot(4000, lambda: self.check(manual=False))

    def check(self, manual=True):
        if self._busy or (not manual and not self.settings.app.get("auto_update", True)):
            return
        self._busy = True

        def work():
            try:
                self._done.emit(updater.latest_release(), None, manual)
            except Exception as exc:          # UpdateError, or anything unexpected - never crash for this
                self._done.emit(None, exc, manual)

        threading.Thread(target=work, name="update-check", daemon=True).start()

    def _finished(self, release, error, manual):
        self._busy = False
        if error is not None:
            log.info("Update check: %s", error)
            if manual:
                self.result.emit("warning", f"Couldn't check for updates: {error}")
            return
        log.info("Update check: latest %s, this is %s", release.version, VERSION)
        if release.newer:
            self.release = release
            self.available.emit(release)
            if manual:
                self.result.emit("info", f"TrueStretch {release.version} is available.")
        elif manual:
            self.result.emit("success", f"You're up to date (version {VERSION}).")


class UpdateBar(Card):
    """Slim bar at the top of the window: 'version X is available' + Update now / Later."""

    def __init__(self, on_update, parent=None):
        super().__init__(padding=12, spacing=0, accent=True, parent=parent)
        self.text = label("", "H3")
        self.sub = label("", "Muted")
        self.btn = button("Update now", "download", "Primary", on_update)
        self.later = button("Later", None, None, self.hide)
        self.add(hbox(vbox(self.text, self.sub, spacing=2), None, self.later, self.btn, spacing=10))
        self.hide()

    def show_release(self, release):
        self.text.setText(f"TrueStretch {release.version} is available")
        self.sub.setText(f"You have {VERSION}. Updating takes a few seconds and keeps all your settings.")
        self.show()


class UpdateDialog(QDialog):
    """What's new + download progress. On success the app restarts into the new version."""
    _progress = Signal(int, int)
    _finished = Signal(object, object)

    def __init__(self, release, parent=None):
        super().__init__(parent)
        self.release = release
        self.setWindowTitle(f"Update {APP_NAME}")
        self.setMinimumSize(520, 420)
        notes = QTextBrowser()
        notes.setOpenExternalLinks(True)
        notes.setMarkdown(release.notes or "Fixes and improvements.")
        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setValue(0)
        self.bar.setTextVisible(False)
        self.bar.hide()
        self.status = label("The new version is checked (SHA-256) before it replaces this one.", "Muted", wrap=True)
        self.go = button("Update and restart", "download", "Primary", self._start)
        self.cancel = button("Not now", None, None, self.reject)
        page = button("Release page", "external", "Link",
                      lambda: QDesktopServices.openUrl(QUrl(release.url)))
        layout = vbox(label(f"What's new in {release.version}", "H2"), notes, self.bar, self.status,
                      hbox(page, None, self.cancel, self.go), spacing=12, margins=(22, 20, 22, 18))
        self.setLayout(layout)
        self._progress.connect(self._on_progress)
        self._finished.connect(self._on_finished)

    def _start(self):
        if updater.installed_exe() is None:       # running from source: just show the release
            QDesktopServices.openUrl(QUrl(self.release.url))
            self.accept()
            return
        self.go.setEnabled(False)
        self.cancel.setEnabled(False)
        self.bar.show()
        self.status.setText("Downloading…")

        def work():
            try:
                exe = updater.install(self.release, lambda d, t: self._progress.emit(d, t))
                self._finished.emit(exe, None)
            except Exception as exc:
                self._finished.emit(None, exc)

        threading.Thread(target=work, name="update-install", daemon=True).start()

    def _on_progress(self, done, total):
        if total:
            self.bar.setValue(int(done * 100 / total))
            self.status.setText(f"Downloading… {done / 1e6:.1f} of {total / 1e6:.1f} MB")

    def _on_finished(self, exe, error):
        if error is not None:
            log.warning("Update failed: %s", error)
            self.status.setText(f"{error} Your current version keeps working.")
            self.go.setEnabled(True)
            self.cancel.setEnabled(True)
            self.go.setText("Try again")
            return
        self.bar.setValue(100)
        self.status.setText("Installed. Restarting…")
        updater.restart_into(exe)
        QTimer.singleShot(300, self._quit)

    def _quit(self):
        self.accept()
        win = self.parent()
        if win is not None and hasattr(win, "quit"):
            win.quit()
        else:
            QApplication.instance().quit()


def open_release_page():
    QDesktopServices.openUrl(QUrl(updater.RELEASES_PAGE))


__all__ = ["UpdateController", "UpdateBar", "UpdateDialog", "open_release_page", "Qt"]
