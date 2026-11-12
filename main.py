"""TrueStretch entry point."""

import ctypes
import getpass
import os
import sys
import traceback
from pathlib import Path


def _point_qt_at_bundled_plugins(log):
    """In the packaged .exe, tell Qt exactly where its plugins (qwindows.dll etc.) were unpacked."""
    roots = [Path(getattr(sys, "_MEIPASS", "")), Path(__file__).resolve().parent, Path(sys.executable).parent]
    for root in roots:
        for rel in ("PySide6/qt-plugins", "PySide6/plugins"):
            plugins = root / rel
            if (plugins / "platforms").is_dir():
                os.environ["QT_PLUGIN_PATH"] = str(plugins)
                os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] = str(plugins / "platforms")
                log.info("Qt plugins: %s", plugins)
                return


def main():
    from truestretch import APP_NAME
    from truestretch.paths import log, setup_logging

    setup_logging()
    if "--watchdog" in sys.argv:                 # guard process: no window, no Qt
        from truestretch import watchdog
        watchdog.run(int(sys.argv[sys.argv.index("--watchdog") + 1]))
        return 0
    if "--update" in sys.argv:                   # check + install from the command line, no window
        from truestretch import updater
        return updater.cli_update()
    if "--wait-pid" in sys.argv:                 # started by an update: let the old version quit first
        from truestretch import updater
        updater.wait_for_pid(int(sys.argv[sys.argv.index("--wait-pid") + 1]))
    log.info("Starting %s", APP_NAME)
    _point_qt_at_bundled_plugins(log)

    from PySide6.QtCore import Qt, qInstallMessageHandler
    from PySide6.QtGui import QGuiApplication

    # Qt's own warnings (missing plugins, graphics problems) go into our log for support.
    qInstallMessageHandler(lambda mode, context, message: log.warning("Qt: %s", message))
    from PySide6.QtNetwork import QLocalServer, QLocalSocket
    from PySide6.QtWidgets import QApplication, QMessageBox, QSystemTrayIcon

    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(f"{APP_NAME}.App")
    except (AttributeError, OSError):
        pass
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setQuitOnLastWindowClosed(False)

    # Only one copy at a time: a second launch just brings the first window forward.
    server_name = f"{APP_NAME}-{getpass.getuser()}"
    probe = QLocalSocket()
    probe.connectToServer(server_name)
    if probe.waitForConnected(300):
        probe.write(b"show")
        probe.flush()
        probe.waitForBytesWritten(300)
        return 0
    QLocalServer.removeServer(server_name)
    server = QLocalServer()
    server.listen(server_name)

    from truestretch.engine import Engine
    from truestretch.games import GAMES
    from truestretch.settings import Settings
    from truestretch.ui import theme
    from truestretch.ui.main_window import MainWindow

    def on_crash(exc_type, exc, tb):
        log.critical("Unexpected error:\n%s", "".join(traceback.format_exception(exc_type, exc, tb)))
        QMessageBox.critical(None, APP_NAME, f"Something went wrong:\n\n{exc}\n\nDetails are in the log "
                             "(My PC › Open log folder). Your settings and backups are safe.")

    sys.excepthook = on_crash

    settings = Settings({g.id: g.default_settings() for g in GAMES})
    theme.load_fonts()
    theme.set_theme(settings.app["theme"])
    app.setStyleSheet(theme.stylesheet())
    engine = Engine(settings)
    window = MainWindow(engine)
    app.aboutToQuit.connect(engine.shutdown)
    from truestretch import watchdog
    watchdog.start_for(os.getpid())          # puts the normal resolution back even if TrueStretch is killed
    from truestretch import VERSION, updater
    updater.cleanup_after_update()
    window.updates.start()

    def on_second_launch():
        conn = server.nextPendingConnection()
        if conn:
            conn.close()
        window.bring_to_front()

    server.newConnection.connect(on_second_launch)

    minimized = "--minimized" in sys.argv or settings.app["start_minimized"]
    if not (minimized and QSystemTrayIcon.isSystemTrayAvailable()):
        window.show()
    from PySide6.QtCore import QTimer
    QTimer.singleShot(500, window.startup if window.isVisible() else window.check_recovery)
    QTimer.singleShot(20000, updater.cleanup_after_update)     # the old copy may still be closing at first
    if "--updated" in sys.argv:
        QTimer.singleShot(1500, lambda: engine.notify(
            "success", f"Updated to TrueStretch {VERSION}. Your settings are just as you left them."))
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
