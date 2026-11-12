"""Home, Backups, Settings and About pages."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QGridLayout, QHeaderView, QLabel, QMessageBox,
                               QTableWidget, QTableWidgetItem)

from .. import APP_NAME, TAGLINE, VERSION, display
from ..games import COMING_SOON
from ..paths import BACKUP_DIR, DATA_DIR
from ..system import open_path, reveal_file, set_startup, startup_enabled
from . import icons
from .base_page import Page, fill_combo, quiet
from .theme import palette
from .widgets import (Badge, Card, CheckRow, Segmented, SettingsGroup, ToggleSwitch, button, clear_layout, divider,
                      game_pixmap, hbox, label, vbox)


# ---------------------------------------------------------------------------
# Home
# ---------------------------------------------------------------------------

class HomePage(Page):
    def __init__(self, engine, window):
        super().__init__(engine, window)
        self.add_header("Home", TAGLINE)

        self.banner = Card(padding=16, accent=True)
        self.banner_icon = QLabel()
        self.banner_title = label("Stretched mode is on", "H3")
        self.banner_detail = label("", "Muted")
        self.banner.add(hbox(self.banner_icon, vbox(self.banner_title, self.banner_detail, spacing=2), None,
                             button("Back to normal now", "undo", None, self._revert), spacing=14))
        self.content.addWidget(self.banner)

        self.game_cards = {}
        for gid, game in engine.games.items():
            card = Card(padding=22, spacing=16)
            icon = QLabel()
            icon.setFixedSize(76, 76)
            name = label(game.name, "H1")
            where = label("", "Muted")
            badges = hbox(spacing=6)
            play = button("Play stretched", "play", "Primary", lambda _=False, g=gid: self.window.play(g))
            play.setMinimumWidth(170)
            configure = button("Settings", "sliders", None, lambda _=False, g=gid: self.window.show_game(g))
            card.add(hbox(icon, vbox(name, where, badges, spacing=4), None,
                          vbox(play, configure, spacing=8), spacing=18))
            card.add(divider())
            card.add(label("Ready to play", "H3"))
            grid = QGridLayout()
            grid.setHorizontalSpacing(24)
            grid.setVerticalSpacing(12)
            rows = []
            for i in range(6):
                row = CheckRow()
                grid.addWidget(row, i // 2, i % 2)
                rows.append(row)
            card.body.addLayout(grid)
            self.content.addWidget(card)
            self.game_cards[gid] = dict(icon=icon, where=where, badges=badges, play=play, rows=rows)

        self.pc_card = Card(padding=18)
        self.pc_icon = QLabel()
        self.pc_title = label("", "H3")
        self.pc_detail = label("", "Muted", wrap=True)
        row = hbox(self.pc_icon, spacing=14)
        row.addLayout(vbox(self.pc_title, self.pc_detail, spacing=2), 1)
        row.addWidget(button("Open My PC", "pulse", None, lambda: self.window.navigate("mypc")))
        self.pc_card.add(row)
        self.content.addWidget(self.pc_card)

        self.content.addSpacing(6)
        self.content.addWidget(label("More games are on the way", "H2"))
        soon = hbox(spacing=12)
        for game in COMING_SOON:
            card = Card(padding=16, spacing=8)
            ic = QLabel()
            ic.setPixmap(game_pixmap(game, None, 40))
            card.add(hbox(ic, vbox(label(game.name, "H3"), label(game.publisher, "Faint"), spacing=1), None,
                          Badge("Soon", "info"), spacing=12))
            soon.addWidget(card)
        self.content.addLayout(soon)
        self.finish()
        self.refresh()

    def _revert(self):
        self.engine.revert_display("you asked")

    def refresh(self):
        engine = self.engine
        p = palette()
        st = engine.state
        self.banner.setVisible(st.stretched)
        if st.stretched:
            mode = display.Mode.from_list(st.data.get("mode"))
            game = engine.games.get(st.data.get("game"))
            self.banner_icon.setPixmap(icons.pixmap("stretch", p["accent"], 26))
            tail = f" when {game.name} closes" if game and engine.gs(game.id).get("revert_on_exit") else ""
            self.banner_detail.setText(f"Desktop is at {mode} — your normal resolution comes back{tail}."
                                       if mode else "Your desktop is stretched.")
        for gid, parts in self.game_cards.items():
            game, info = engine.games[gid], engine.info[gid]
            parts["icon"].setPixmap(game_pixmap(game, info, 76))
            parts["where"].setText(f"{game.publisher}  ·  " + (str(info.install_dir) if info.installed
                                                                    else "not found on this PC"))
            badges = parts["badges"]
            clear_layout(badges)
            if engine.running.get(gid):
                badges.addWidget(Badge("Running", "success"))
            if engine.is_stretched(gid):
                badges.addWidget(Badge("Stretched", "accent"))
            if info.region:
                badges.addWidget(Badge(info.region, "info"))
            gs = engine.gs(gid)
            badges.addWidget(Badge(f"{gs['width']} × {gs['height']}", "info"))
            badges.addStretch(1)
            checks = engine.checks(gid)
            for row, check in zip(parts["rows"], checks):
                row.set(check.title, check.ok, check.detail)
            parts["play"].setEnabled(not engine.running.get(gid))

        from .. import health
        gid = next(iter(engine.games))
        items = health.checks(engine, gid)
        todo = [i for i in items if i.status in (health.WARN, health.BAD)]
        pc = engine.pc
        hw = " · ".join(x for x in [pc.gpus[0].name if pc.gpus else "", f"{round(pc.ram_gb)} GB RAM"
                                         if pc.ram_gb else "", pc.windows] if x)
        if todo:
            self.pc_icon.setPixmap(icons.pixmap("alert", p["warning"], 26))
            self.pc_title.setText(f"PC check: {len(todo)} thing{'s' if len(todo) > 1 else ''} to improve")
            self.pc_detail.setText(", ".join(i.title for i in todo[:2]) + ("…" if len(todo) > 2 else ""))
        else:
            self.pc_icon.setPixmap(icons.pixmap("check-circle", p["success"], 26))
            self.pc_title.setText("PC check: everything looks great")
            self.pc_detail.setText(hw)


# ---------------------------------------------------------------------------
# Backups
# ---------------------------------------------------------------------------

class BackupsPage(Page):
    def __init__(self, engine, window):
        super().__init__(engine, window)
        self.add_header("Backups", "Every settings file is copied before TrueStretch changes it. The original "
                        "(from before TrueStretch ever touched it) is always kept.")
        card = Card()
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Settings file", "Kind", "Saved", "Game"])
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setMinimumHeight(360)
        h = self.table.horizontalHeader()
        h.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        h.setSectionResizeMode(0, QHeaderView.Stretch)
        for col, width in ((1, 110), (2, 170), (3, 120)):
            h.setSectionResizeMode(col, QHeaderView.Fixed)
            h.resizeSection(col, width)
        self.table.itemSelectionChanged.connect(self._selection_changed)
        self.size_label = label("", "Faint")
        self.btn_restore = button("Restore this backup", "undo", "Primary", self._restore)
        self.btn_show = button("Show file", "folder", None, self._show)
        self.btn_delete = button("Delete", "trash", "Danger", self._delete)
        self.empty = label("No backups yet. The first time you press Play stretched, a copy of every settings file "
                           "is saved here before anything changes.", "Muted", wrap=True)
        self.empty.setAlignment(Qt.AlignCenter)
        card.add(self.table, self.empty,
                 hbox(self.size_label, None, self.btn_delete, self.btn_show, self.btn_restore, spacing=8))
        self.content.addWidget(card)
        self.content.addLayout(hbox(None, button("Open backups folder", "external", "Ghost",
                                                 lambda: open_path(BACKUP_DIR))))
        self.finish()
        self.backups = []
        self.refresh()

    def refresh(self):
        self.backups = self.engine.backups.list()
        self.table.setRowCount(len(self.backups))
        names = {gid: g.name for gid, g in self.engine.games.items()}
        for row, b in enumerate(self.backups):
            nick = self.engine.settings.data["games"].get(b.game_id, {}).get("nicknames", {}).get(b.target_key)
            cells = [nick or b.target_label, "Original" if b.kind == "original" else "Automatic",
                     b.created.strftime("%d %b %Y, %H:%M:%S"), names.get(b.game_id, b.game_id)]
            for col, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if col == 0:
                    item.setToolTip(str(b.target_path))
                self.table.setItem(row, col, item)
        self.table.setVisible(bool(self.backups))
        self.empty.setVisible(not self.backups)
        self.empty.setMinimumHeight(0 if self.backups else 160)
        size = self.engine.backups.size_bytes()
        self.size_label.setText(f"{len(self.backups)} backups · {size / 1024:.0f} KB")
        self._selection_changed()

    def _selected(self):
        rows = self.table.selectionModel().selectedRows()
        return self.backups[rows[0].row()] if rows else None

    def _selection_changed(self):
        b = self._selected()
        for btn in (self.btn_restore, self.btn_show):
            btn.setEnabled(b is not None)
        self.btn_delete.setEnabled(b is not None and b.kind != "original")

    def _restore(self):
        b = self._selected()
        if not b:
            return
        game = self.engine.games.get(b.game_id)
        if game and self.engine.running.get(b.game_id):
            QMessageBox.warning(self, APP_NAME, f"Close {game.name} first.")
            return
        if QMessageBox.question(self, APP_NAME, f"Put this backup back?\n\n{b.target_path}\n\n"
                                "The current file is backed up first.") != QMessageBox.Yes:
            return
        try:
            if b.target_path.exists():
                self.engine.backups.create(b.game_id, b.target_key, b.target_label, b.target_path)
            self.engine.backups.restore(b)
            self.engine.notify("success", "Backup restored.")
        except OSError as exc:
            self.engine.notify("error", f"Couldn't restore the backup: {exc}")
        self.engine.changed.emit()

    def _show(self):
        b = self._selected()
        if b:
            reveal_file(b.path)

    def _delete(self):
        b = self._selected()
        if b and QMessageBox.question(self, APP_NAME, "Delete this backup?") == QMessageBox.Yes:
            self.engine.backups.delete(b)
            self.refresh()


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

class SettingsPage(Page):
    def __init__(self, engine, window):
        super().__init__(engine, window)
        self.add_header("Settings", "How TrueStretch itself behaves.")

        look = SettingsGroup("Appearance")
        self.theme_seg = Segmented([("dark", "Dark"), ("light", "Light"), ("system", "Match Windows")])
        self.theme_seg.changed.connect(self._theme)
        look.add_row("Theme", None, self.theme_seg, "sparkle")
        self.content.addWidget(look)

        behaviour = SettingsGroup("Behaviour")
        self.t_startup = self._toggle(behaviour, "Start with Windows", "Sits in the tray, ready when you want to play.",
                                      "power", self._startup)
        self.t_minimized = self._toggle(behaviour, "Start minimized to the tray",
                                        "Opens quietly in the background instead of showing the window.", "minimize",
                                        lambda on: self._set("start_minimized", on))
        self.t_tray = self._toggle(behaviour, "Closing the window keeps TrueStretch in the tray",
                                   "So it can still switch your resolution back when the game closes.", "tray",
                                   lambda on: self._set("close_to_tray", on))
        self.t_notify = self._toggle(behaviour, "Notifications", "Show a notification when the resolution changes "
                                     "while the window is hidden.", "bell", lambda on: self._set("notifications", on))
        self.content.addWidget(behaviour)

        safety = SettingsGroup("Safety")
        self.t_confirm = self._toggle(safety, "Ask before keeping a new resolution",
                                      "Like Windows does: if you can't see the screen, it switches back by itself.",
                                      "shield", lambda on: self._set("confirm_display_change", on))
        self.confirm_secs = QComboBox()
        self.confirm_secs.currentIndexChanged.connect(
            lambda _: self._set("confirm_seconds", self.confirm_secs.currentData()))
        safety.add_row("Switch back after", "How long you have to press “Keep it”.", self.confirm_secs, "clock")
        self.keep = QComboBox()
        self.keep.currentIndexChanged.connect(self._keep_changed)
        safety.add_row("Automatic backups to keep (per file)", "The original backup is always kept on top of these.",
                       self.keep, "archive")
        self.content.addWidget(safety)

        updates = SettingsGroup("Updates")
        self.t_update = self._toggle(updates, "Check for updates automatically",
                                     "Asks GitHub for a newer version when TrueStretch starts. Nothing about you or "
                                     "your PC is sent.", "download", lambda on: self._set("auto_update", on))
        updates.add_row(f"Version {VERSION}", "Updates are checked (SHA-256) before they replace this version.",
                        hbox(button("Check now", "refresh", None, lambda: self.window.open_update()),
                             button("Release notes", "external", None, self._release_notes), spacing=8), "sparkle")
        self.content.addWidget(updates)

        help_group = SettingsGroup("Help")
        help_group.add_row("Welcome tour", "Scan your PC again and walk through the setup from the start.",
                           button("Show again", "sparkle", None, lambda: self.window.show_welcome()), "book")
        help_group.add_row("Support file", "Something not working? Creates a zip on your Desktop with TrueStretch's "
                           "logs to attach to a bug report. No passwords or account details.",
                           button("Create", "lifebuoy", None, self._support_file), "lifebuoy")
        help_group.add_row("Report a problem", "Opens the bug report form on GitHub.",
                           button("Open", "external", None, self._report), "external")
        self.content.addWidget(help_group)

        data = SettingsGroup("Data")
        data.add_row("TrueStretch folder", str(DATA_DIR),
                     button("Open", "folder", None, lambda: open_path(DATA_DIR)), "folder")
        data.add_row("Reset all settings", "Back to defaults. Backups and your game files aren't touched.",
                     button("Reset", "undo", "Danger", self._reset), "undo")
        self.content.addWidget(data)
        self.finish()
        self.refresh()

    def _toggle(self, group, title, desc, icon_name, handler):
        t = ToggleSwitch()
        t.toggled.connect(handler)
        group.add_row(title, desc, t, icon_name)
        return t

    def _set(self, key, value):
        self.engine.settings.app[key] = value
        self.engine.save()

    def _theme(self, name):
        self._set("theme", name)
        self.window.apply_theme()

    def _startup(self, on):
        try:
            set_startup(on)
            self._set("start_with_windows", on)
        except OSError as exc:
            self.engine.notify("error", f"Couldn't change the startup setting: {exc}")
            self.refresh()

    def _release_notes(self):
        from .update import open_release_page
        open_release_page()

    def _report(self):
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        from ..updater import REPO
        QDesktopServices.openUrl(QUrl(f"https://github.com/{REPO}/issues/new/choose"))

    def _support_file(self):
        from ..support import create_support_file
        try:
            path = create_support_file(self.engine)
        except OSError as exc:
            self.engine.notify("error", f"Couldn't create the support file: {exc}")
            return
        self.engine.notify("success", f"Support file saved: {path.name} (on your Desktop).")
        reveal_file(path)

    def _keep_changed(self, _):
        self._set("keep_backups", self.keep.currentData())
        self.engine.backups.keep = self.keep.currentData()

    def _reset(self):
        if QMessageBox.question(self, APP_NAME, "Reset all TrueStretch settings to their defaults?") == QMessageBox.Yes:
            self.engine.settings.reset()
            set_startup(False)
            self.window.apply_theme()
            self.engine.notify("success", "Settings reset.")
            self.engine.changed.emit()

    def refresh(self):
        app = self.engine.settings.app
        with quiet(self.t_update):
            self.t_update.setChecked(bool(app.get("auto_update", True)))
        with quiet(self.theme_seg, self.t_startup, self.t_minimized, self.t_tray, self.t_notify, self.t_confirm):
            self.theme_seg.set_value(app["theme"])
            self.t_startup.setChecked(startup_enabled())
            self.t_minimized.setChecked(app["start_minimized"])
            self.t_tray.setChecked(app["close_to_tray"])
            self.t_notify.setChecked(app["notifications"])
            self.t_confirm.setChecked(app["confirm_display_change"])
        fill_combo(self.confirm_secs, [(f"{s} seconds", s) for s in (10, 15, 20, 30)], app["confirm_seconds"])
        fill_combo(self.keep, [(str(n), n) for n in (5, 10, 15, 30, 50)], app["keep_backups"])
        self.confirm_secs.setEnabled(app["confirm_display_change"])


# ---------------------------------------------------------------------------
# About
# ---------------------------------------------------------------------------

RIOT_LEGAL = ("TrueStretch isn't endorsed by Riot Games and doesn't reflect the views or opinions of Riot Games or "
              "anyone officially involved in producing or managing Riot Games properties. Riot Games, VALORANT, and "
              "all associated properties are trademarks or registered trademarks of Riot Games, Inc. Game icons are "
              "loaded from your own installation and are not distributed with TrueStretch.")

FAIR_PLAY = ("TrueStretch only changes your Windows display resolution and the game's own settings file — the "
             "same things you'd change by hand. It never touches the game while it's running, never reads or "
             "modifies game memory, and never interacts with anti-cheat. Riot doesn't officially support true "
             "stretched resolution, and some players have reported account penalties after using it. "
             "Use it at your own risk.")


class AboutPage(Page):
    def __init__(self, engine, window):
        super().__init__(engine, window)
        logo = QLabel()
        logo.setPixmap(window.logo_pixmap(84))
        self.content.addLayout(hbox(logo, vbox(label(APP_NAME, "PageTitle"), label(f"Version {VERSION}", "Muted"),
                                               label(TAGLINE, "Muted"), spacing=2), None, spacing=20))
        how = Card()
        how.add(label("How it works", "H2"))
        for i, text in enumerate([
            "Before VALORANT starts: turns the monitor drivers off, adds the stretched resolution to your graphics "
            "driver and sets its scaling to full screen, and puts VALORANT on Windowed fullscreen + Fill.",
            "VALORANT starts at your screen's normal resolution, so menus and agent select look normal.",
            "As soon as a match (or the Range) has loaded, your desktop switches to the stretched resolution and "
            "the graphics card stretches it across the whole screen. When a match is found or you go back to the "
            "menu, it switches back first.",
            "Backs up every file before changing it, and a guard puts your normal resolution back even if "
            "TrueStretch crashes.",
        ], 1):
            num = label(f"{i}.", "H3")
            num.setFixedWidth(18)
            row = hbox(num, spacing=8)
            row.addWidget(label(text, "Muted", wrap=True), 1)
            how.add(row)
        self.content.addWidget(how)
        self.content.addWidget(Card().add(hbox(_icon_label("shield", "warning"), label("Fair play", "H2"), None),
                                          label(FAIR_PLAY, "Muted", wrap=True)))
        self.content.addWidget(Card().add(label("Legal", "H2"), label(RIOT_LEGAL, "Faint", wrap=True)))
        self.finish()


def _icon_label(name, color_key):
    lbl = QLabel()
    lbl.setPixmap(icons.pixmap(name, palette()[color_key], 20))
    return lbl
