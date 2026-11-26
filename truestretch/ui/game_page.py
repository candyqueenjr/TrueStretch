"""The per-game page: what you'll play at (stretch size) first, everything else in tabs below."""

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QAbstractItemView, QButtonGroup, QComboBox, QDialog, QHeaderView, QLabel,
                               QMessageBox, QScrollArea, QSpinBox, QTabWidget, QTreeWidget, QTreeWidgetItem, QWidget)

from .. import APP_NAME, display
from ..engine import StretchError
from ..guides import open_display_settings
from ..system import open_path
from . import icons
from .base_page import Page, fill_combo, quiet
from .theme import palette
from .responsive import Reflow, ResponsiveGrid
from .color_tab import ColorTab
from .servers_tab import ServersTab
from .widgets import (Badge, Card, CheckRow, ResolutionTile, Segmented, SettingsGroup, ToggleSwitch, button,
                      divider, game_pixmap, hbox, label, vbox)

# What players actually run into, with the fix in plain words. Shown in the Troubleshooting window, which opens
# from the Stretch tab and by itself after a Test stretch that didn't fill the screen.
PROBLEMS = [
    ("Black bars at the left and right",
     "The graphics driver is keeping the 16:9 shape. TrueStretch sets Full-screen scaling by itself when you press "
     "Play or Test stretch — press Test stretch again. If the bars stay, restart the PC once (some drivers only "
     "pick up the scaling change after a restart).", "test"),
    ("Black bars at the top and bottom in a match",
     "VALORANT is letterboxing: the desktop switched too early. Press Ctrl+Alt+S twice (native, then stretched "
     "again) once the round has started.", None),
    ("Picture fills the screen but players look normal",
     "The stretch was applied before the match loaded, so VALORANT squeezed it back. Press Ctrl+Alt+S twice in the "
     "round, or leave “Stretch automatically in matches” on so it switches at the right moment.", None),
    ("I want more (or less) stretch",
     "In a match press Ctrl+Alt+↑ for more and Ctrl+Alt+↓ for less — it switches instantly and remembers your "
     "choice.", None),
    ("Black bars only on the loading screen",
     "Normal — the stretch starts when the map has loaded.", None),
    ("Picture looks blurry",
     "Keep the same height as your screen (1080 on a 1080p screen) — every stretch size here does.", None),
    ("My screen went black after switching",
     "Wait — it switches back by itself after the countdown. You can also press Restore normal.", None),
    ("The hotkeys don't do anything",
     "Another program (often a recording or overlay app) already uses Ctrl+Alt+S / Ctrl+Alt+↑ / ↓. Close it and "
     "restart TrueStretch. Automatic stretching in matches keeps working without the hotkeys.", None),
]


class TroubleshootDialog(QDialog):
    def __init__(self, parent, on_test=None, intro=None):
        super().__init__(parent)
        self.setWindowTitle(f"{APP_NAME} — Troubleshooting")
        self.setWindowFlag(Qt.WindowContextHelpButtonHint, False)
        self.setMinimumSize(640, 560)
        body = QWidget()
        body.setObjectName("Transparent")
        rows = vbox(spacing=0)
        for title, text, action in PROBLEMS:
            row = hbox(spacing=14, margins=(0, 12, 0, 12))
            row.addLayout(vbox(label(title, "H3"), label(text, "Muted", wrap=True), spacing=3), 1)
            if action == "test" and on_test:
                row.addWidget(button("Test stretch", "monitor", None, lambda: (self.accept(), on_test())), 0,
                              Qt.AlignVCenter)
            rows.addWidget(divider())
            rows.addLayout(row)
        body.setLayout(rows)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(body)
        head = vbox(label("Troubleshooting", "H1"), spacing=4)
        if intro:
            head.addWidget(label(intro, "Muted", wrap=True))
        self.setLayout(vbox(head, scroll, hbox(None, button("Close", None, None, self.accept)),
                            spacing=12, margins=(24, 20, 24, 18)))


GET_GAME = {"valorant": "https://playvalorant.com/download/"}


def tab_page():
    w = QWidget()
    w.setObjectName("Transparent")
    layout = vbox(spacing=16, margins=(0, 16, 0, 0))
    w.setLayout(layout)
    return w, layout


class GamePage(Page):
    def __init__(self, engine, window, game_id):
        super().__init__(engine, window)
        self.gid = game_id
        self.game = engine.games[game_id]
        self._checks_open = False
        self._tree_key = None
        self._build_header()
        self._build_action_card()
        self.tabs = QTabWidget()
        from .theme import button_font
        self.tabs.tabBar().setFont(button_font(10.5, spacing=1.6))
        self.tabs.setDocumentMode(True)
        self.content.addWidget(self.tabs)
        self._build_resolution_tab()
        self._build_servers_tab()
        self._build_color_tab()
        self._build_accounts_tab()
        self._build_display_tab()
        self._build_launch_tab()
        self.finish()
        self.refresh()
        self.tabs.currentChanged.connect(self._tab_switched)

    def _tab_switched(self, _index):
        """Each tab fills itself only while it's on screen, so opening one must refresh it (Accounts, Display and
        Launch used to show what they had at the last engine change until something else happened)."""
        refresh = getattr(self.window, "_refresh_page", None)
        if refresh and self.isVisible():
            refresh(self)

    @property
    def gs(self):
        return self.engine.gs(self.gid)

    def _set(self, key, value):
        self.gs[key] = value
        self.engine.save()

    # ---- header & status ---------------------------------------------------

    def _build_header(self):
        """One compact row: icon, name + live status, version/path, Rescan. The stretch sizes start right below."""
        self.icon = QLabel()
        self.icon.setFixedSize(44, 44)
        self.title = label(self.game.name, "PageTitle")
        self.subtitle = label("", "Faint")
        self.subtitle.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.subtitle.setWordWrap(True)
        self.status = Badge("", "info")
        rescan = button("Rescan", "refresh", "Ghost", lambda: self.engine.refresh())
        rescan.setToolTip("Look for the game, its settings files and your displays again")
        text = vbox(hbox(self.title, self.status, None, spacing=14), self.subtitle, spacing=0)
        row = hbox(self.icon, spacing=14)
        row.addLayout(text, 1)
        row.addWidget(rescan, 0, Qt.AlignVCenter)
        self.content.addLayout(row)

    def _build_action_card(self):
        card = Card(padding=18, spacing=10, accent=True)
        self.summary_caption = label("Ready to play", "Caption")
        self.summary_title = label("", "H2")
        self.summary_title.setWordWrap(True)
        self.summary_detail = label("", "Muted")
        self.summary_detail.setWordWrap(True)
        self.btn_restore = button("Restore normal", "undo", "Ghost", lambda: self.window.restore(self.gid),
                                  "Put back your original game settings and normal desktop resolution")
        self.btn_apply = button("Test stretch", "monitor", None, lambda: self.window.test_stretch(self.gid),
                                "Stretch the desktop for 15 seconds so you can see whether your screen fills")
        top = Reflow(breakpoint=720, spacing=10)
        top.add(vbox(self.summary_caption, self.summary_title, self.summary_detail, spacing=3), 1)
        top.add(hbox(self.btn_restore, self.btn_apply, spacing=8))

        # Checks: one line when everything is fine ("All 6 checks passed · Show"), the full list when something
        # needs attention - no wall of green ticks pushing the stretch sizes off the screen.
        self.checks_icon = QLabel()
        self.checks_line = label("", "Muted")
        self.checks_toggle = button("Show", None, "Subtle", self._toggle_checks)
        # The one fix the page can't do by itself: when the game isn't on this PC, offer the download right here.
        self.btn_get = button(f"Get {self.game.name}", "external", None,
                              lambda: QDesktopServices.openUrl(QUrl(GET_GAME.get(self.gid, ""))),
                              f"Opens the official {self.game.name} download page. Install it, then press Rescan.")
        self.btn_get.hide()
        self.checks_bar = QWidget()
        self.checks_bar.setObjectName("Transparent")
        self.checks_bar.setLayout(hbox(self.checks_icon, self.checks_line, self.checks_toggle, None, self.btn_get,
                                       spacing=8))
        self.checks_grid = ResponsiveGrid(min_width=290, max_cols=3, spacing=14)
        self.check_rows = []
        card.add(top, divider(), self.checks_bar, self.checks_grid)
        self.content.addWidget(card)

    def _toggle_checks(self):
        self._checks_open = not self._checks_open
        self.refresh()

    # ---- tab: stretch -----------------------------------------------------

    TAB_KEYS = ["resolution", "servers", "color", "accounts", "display", "launch"]   # in the order they're built

    def show_tab(self, name):
        keys = self.TAB_KEYS
        self.tabs.setCurrentIndex(keys.index(name) if name in keys else 0)

    def current_tab(self):
        i = self.tabs.currentIndex()
        return self.TAB_KEYS[i] if 0 <= i < len(self.TAB_KEYS) else "resolution"

    def troubleshoot(self, intro=None):
        TroubleshootDialog(self, lambda: self.window.test_stretch(self.gid), intro).exec()

    def _build_resolution_tab(self):
        page, layout = tab_page()
        card = Card()
        card.add(label("Stretched resolution", "H2"),
                 label("What your desktop switches to once a match has loaded — narrower means wider player models. "
                       "Change it live in a match with Ctrl+Alt+↑ (more) and Ctrl+Alt+↓ (less).", "Muted",
                       wrap=True))
        grid = ResponsiveGrid(min_width=180, max_cols=5, spacing=10)
        self.tile_group = QButtonGroup(self)
        self.tiles = []
        for preset in self.game.presets:
            tile = ResolutionTile(f"{preset.width} × {preset.height}", f"{preset.aspect} · {preset.note}")
            tile.clicked.connect(lambda _=False, p=preset: self._pick_size(p.width, p.height))
            self.tile_group.addButton(tile)
            self.tiles.append((tile, preset))
            grid.add(tile)
        self.custom_tile = ResolutionTile("Custom", "Any size you like")
        self.custom_tile.clicked.connect(self._pick_custom)
        self.tile_group.addButton(self.custom_tile)
        grid.add(self.custom_tile)
        card.body.addWidget(grid)

        self.custom_w = self._spin(640, 7680)
        self.custom_h = self._spin(480, 4320)
        self.custom_row = QWidget()
        self.custom_row.setObjectName("Transparent")
        self.custom_row.setLayout(hbox(label("Width", "Muted"), self.custom_w, label("×", "Muted"),
                                       label("Height", "Muted"), self.custom_h, None, spacing=8))
        card.add(self.custom_row)

        self.avail = CheckRow()
        foot = Reflow(breakpoint=640, spacing=8)
        foot.add(self.avail, 1)
        foot.add(hbox(button("Black bars or no stretch?", "info", "Ghost", lambda: self.troubleshoot()),
                      button("Re-check display", "refresh", "Ghost", self.engine.refresh), spacing=4))
        card.add(foot)
        layout.addWidget(card)

        opts = SettingsGroup("Options")
        self.refresh_combo = QComboBox()
        self.refresh_combo.setMinimumWidth(210)
        self.refresh_combo.currentIndexChanged.connect(
            lambda _: self._set("refresh", self.refresh_combo.currentData()))
        opts.add_row("Refresh rate", "Highest available is best for aim. Only rates your display offers are listed.",
                     self.refresh_combo, "monitor")
        self.mode_seg = Segmented([(k, v[0]) for k, v in self.game.window_modes.items()])
        self.mode_seg.changed.connect(lambda k: self._set("window_mode", k))
        opts.add_row("Display mode in game", "Windowed fullscreen follows the desktop when it switches mid-match "
                     "— that's what true stretched needs.", self.mode_seg, "stretch")
        self.auto_toggle = ToggleSwitch()
        self.auto_toggle.toggled.connect(lambda on: self._set("auto_match", on))
        opts.add_row("Stretch automatically in matches",
                     "Native resolution in menus, agent select and loading; stretched as soon as the map has "
                     "loaded; back to native when you return to the menu. Ctrl+Alt+S switches by hand any time.",
                     self.auto_toggle, "wand")
        layout.addWidget(opts)
        layout.addStretch(1)
        self.tabs.addTab(page, "Stretch")

    def _spin(self, lo, hi):
        spin = QSpinBox()
        spin.setRange(lo, hi)
        spin.setButtonSymbols(QSpinBox.NoButtons)
        spin.setFixedWidth(90)
        spin.setAlignment(Qt.AlignCenter)
        spin.editingFinished.connect(self._custom_changed)
        return spin

    def _pick_size(self, w, h):
        self.gs["width"], self.gs["height"] = w, h
        self.gs["refresh"] = "max"
        self.engine.save()

    def _pick_custom(self):
        self.custom_row.setVisible(True)
        self.custom_w.setFocus()

    def _custom_changed(self):
        w, h = self.custom_w.value(), self.custom_h.value()
        if (w, h) != (int(self.gs["width"]), int(self.gs["height"])):
            self._pick_size(w, h)

    # ---- tab: accounts ----------------------------------------------------

    def _build_servers_tab(self):
        """The ping board: VALORANT's own ping to every server, kept by TrueStretch (ui/servers_tab.py)."""
        page, layout = tab_page()
        self.servers = ServersTab(self.engine, self.gid, self.window)
        layout.addWidget(self.servers)
        layout.addStretch(1)
        self.tabs.addTab(page, "Servers")

    def _build_color_tab(self):
        """Game Color: vivid colours only while VALORANT is in front (ui/color_tab.py)."""
        page, layout = tab_page()
        self.color = ColorTab(self.engine, self.gid, self.window)
        layout.addWidget(self.color)
        layout.addStretch(1)
        self.tabs.addTab(page, "Color")

    def _build_accounts_tab(self):
        page, layout = tab_page()
        card = Card()
        card.add(label("Your VALORANT accounts", "H2"),
                 label("Every account that has signed in on this PC has its own settings file, plus one for new "
                       "accounts. Ticked accounts get stretched. Give them names so you know which is which.",
                       "Muted", wrap=True))
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Name", "Last played", "Stretch setting", "Locked"])
        self.tree.setRootIsDecorated(False)
        self.tree.setAlternatingRowColors(False)
        self.tree.setSelectionMode(QAbstractItemView.SingleSelection)
        self.tree.setEditTriggers(QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed)
        self.tree.setMinimumHeight(220)
        header = self.tree.header()
        header.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        for col, width in ((1, 190), (2, 200), (3, 80)):
            header.setSectionResizeMode(col, QHeaderView.Fixed)
            header.resizeSection(col, width)
        self.tree.itemChanged.connect(self._tree_changed)
        self.tree.itemSelectionChanged.connect(lambda: self.btn_rename.setEnabled(self._renamable() is not None))
        card.add(self.tree)
        self.btn_rename = button("Rename", "edit", None, self._rename, "Give the selected account a name")
        self.btn_rename.setEnabled(False)
        actions = Reflow(breakpoint=760, spacing=8)
        actions.add(hbox(self.btn_rename,
                         button("Select all", None, "Ghost", lambda: self._select_all(True)),
                         button("Select none", None, "Ghost", lambda: self._select_all(False)), spacing=8))
        actions.add(None)
        actions.add(hbox(button("Open settings folder", "folder", "Ghost",
                                lambda: open_path(self.engine.info[self.gid].config_root or ".")),
                         button("Reset settings files", "trash", "Danger", self._reset_files,
                                "Delete the ticked files (backed up first) so VALORANT starts clean — fixes a "
                                "greyed-out Fill option"), spacing=8))
        card.add(actions)
        layout.addWidget(card)
        layout.addStretch(1)
        self.tabs.addTab(page, "Accounts")

    def _renamable(self):
        items = self.tree.selectedItems()
        return items[0] if items and items[0].data(0, Qt.UserRole) else None

    def _rename(self):
        item = self._renamable()
        if item is not None:
            self.tree.editItem(item, 0)

    def _tree_changed(self, item, column):
        key = item.data(0, Qt.UserRole)
        if column != 0 or not key:
            return
        excluded = set(self.gs.get("excluded", []))
        if item.checkState(0) == Qt.Checked:
            excluded.discard(key)
        else:
            excluded.add(key)
        self.gs["excluded"] = sorted(excluded)
        nickname = item.text(0).strip()
        default_label = item.data(0, Qt.UserRole + 1)
        nicknames = self.gs.setdefault("nicknames", {})
        if nickname and nickname != default_label:
            nicknames[key] = nickname
        else:
            nicknames.pop(key, None)
            if not nickname:
                with quiet(self.tree):
                    item.setText(0, default_label)
        self._tree_key = None
        self.engine.save()

    def _select_all(self, on):
        keys = [t.key for t in self.engine.targets(self.gid)]
        self.gs["excluded"] = [] if on else keys
        self.engine.save()

    def _fill_tree(self, targets):
        """Rebuild the account list only when something in it changed, and never while a name is being edited
        (the list used to be rebuilt on every refresh, which cancelled a rename halfway and lost the selection)."""
        gs = self.gs
        excluded = set(gs.get("excluded", []))
        names = [self.engine.target_name(self.gid, t) for t in targets]
        key = tuple((t.key, n, t.current, t.read_only, t.last_signed_in, t.last_used, t.key in excluded)
                    for t, n in zip(targets, names))
        if key == self._tree_key or self.tree.state() == QAbstractItemView.EditingState:
            return
        self._tree_key = key
        selected = self._renamable()
        selected_key = selected.data(0, Qt.UserRole) if selected is not None else None
        p = palette()
        with quiet(self.tree):
            self.tree.clear()
            for t, name in zip(targets, names):
                when = t.last_used.strftime("%d %b %Y, %H:%M") + ("  ·  last signed in" if t.last_signed_in else "")
                item = QTreeWidgetItem([name, when, t.current, "Yes" if t.read_only else ""])
                item.setData(0, Qt.UserRole, t.key)
                item.setData(0, Qt.UserRole + 1, t.label)
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsEditable)
                item.setCheckState(0, Qt.Unchecked if t.key in excluded else Qt.Checked)
                item.setIcon(0, icons.icon("user" if not t.is_default else "sparkle", p["muted"], 16))
                item.setToolTip(0, "Double-click or press Rename to give this account a name")
                self.tree.addTopLevelItem(item)
                if t.key == selected_key:
                    item.setSelected(True)
            if not targets:
                item = QTreeWidgetItem(["No settings files yet — press Play stretched; they're set up after your "
                                        "first session", "", "", ""])
                item.setFlags(Qt.NoItemFlags)
                self.tree.addTopLevelItem(item)
        self.tree.setColumnHidden(3, not any(t.read_only for t in targets))
        self.btn_rename.setEnabled(self._renamable() is not None)

    # ---- tab: display -----------------------------------------------------

    def _build_display_tab(self):
        page, layout = tab_page()
        group = SettingsGroup("Display")
        self.monitor_combo = QComboBox()
        self.monitor_combo.setMinimumWidth(300)
        self.monitor_combo.currentIndexChanged.connect(
            lambda _: self._set("display", self.monitor_combo.currentData()))
        group.add_row("Monitor", "The screen you play VALORANT on.", self.monitor_combo, "monitor")
        self.normal_combo = QComboBox()
        self.normal_combo.setMinimumWidth(300)
        self.normal_combo.currentIndexChanged.connect(
            lambda _: self._set("normal", self.normal_combo.currentData()))
        group.add_row("Normal resolution", "What your desktop goes back to after playing.", self.normal_combo, "undo")
        self.desktop_now = label("", "Muted")
        group.add_row("Right now", None, self.desktop_now, "pulse")
        layout.addWidget(group)

        auto = SettingsGroup("Switching back")
        self.revert_exit = ToggleSwitch()
        self.revert_exit.toggled.connect(lambda on: self._set("revert_on_exit", on))
        auto.add_row("When VALORANT closes", "Put your normal resolution back as soon as the game exits.",
                     self.revert_exit, "gamepad")
        self.revert_app = ToggleSwitch()
        self.revert_app.toggled.connect(lambda on: self._set("revert_on_app_exit", on))
        auto.add_row("When TrueStretch quits", "Never leave your desktop stretched by accident.", self.revert_app,
                     "power")
        layout.addWidget(auto)

        scaling = SettingsGroup("Graphics driver")
        self.auto_scaling_toggle = ToggleSwitch()
        self.auto_scaling_toggle.toggled.connect(lambda on: self._set("auto_scaling", on))
        scaling.add_row("Set full-screen scaling automatically",
                        "When you press Play, TrueStretch tells your NVIDIA, AMD or Intel driver to stretch the "
                        "picture to the full screen (no black bars) and puts your setting back afterwards. Leave "
                        "this on unless you set scaling yourself.", self.auto_scaling_toggle, "wand")
        self.gpu_line = label("", "Muted", wrap=True)
        scaling.add_row("Your graphics", None, self.gpu_line, "monitor")
        layout.addWidget(scaling)
        layout.addWidget(Card().add(hbox(
            label("Need to change Windows scaling or arrange screens?", "Muted"), None,
            button("Windows display settings", "external", None, open_display_settings), spacing=8)))
        layout.addStretch(1)
        self.tabs.addTab(page, "Display")

    # ---- tab: launch & tweaks ---------------------------------------------

    def _build_launch_tab(self):
        page, layout = tab_page()
        launch = SettingsGroup("Launching")
        self.patch_combo = QComboBox()
        self.patch_combo.setMinimumWidth(200)
        self.patch_combo.currentIndexChanged.connect(lambda _: self._set("patchline", self.patch_combo.currentData()))
        launch.add_row("Server", "Which VALORANT the Riot Client starts (Live unless you test on the PBE).",
                       self.patch_combo, "gamepad")
        self.timeout_combo = QComboBox()
        self.timeout_combo.setMinimumWidth(200)
        self.timeout_combo.currentIndexChanged.connect(
            lambda _: self._set("launch_timeout_min", self.timeout_combo.currentData()))
        launch.add_row("Give up waiting after", "If the game hasn't started by then (for example you closed the Riot "
                       "Client), your normal resolution comes back.", self.timeout_combo, "pulse")
        layout.addWidget(launch)

        self.tweak_group = SettingsGroup("Windows tweaks", "Optional settings that help stretched res work "
                                         "reliably. They only affect VALORANT and can be turned off any time.")
        self.tweak_toggles = {}
        for tweak in self.game.tweaks(self.engine.info[self.gid]):
            toggle = ToggleSwitch()
            toggle.toggled.connect(lambda on, t=tweak.id: self._set_tweak(t, on))
            self.tweak_toggles[tweak.id] = toggle
            self.tweak_group.add_row(tweak.title, tweak.description, toggle, "wand")
        layout.addWidget(self.tweak_group)
        layout.addStretch(1)
        self.tabs.addTab(page, "Launch && tweaks")

    def _set_tweak(self, tweak_id, on):
        for tweak in self.game.tweaks(self.engine.info[self.gid]):
            if tweak.id == tweak_id:
                try:
                    tweak.set_on(on)
                    self.engine.notify("success", f"{tweak.title}: {'on' if on else 'off'}.")
                except OSError as exc:
                    self.engine.notify("error", f"Couldn't change “{tweak.title}”: {exc}")
        self.refresh()

    def _reset_files(self):
        box = QMessageBox(self)
        box.setWindowTitle(APP_NAME)
        box.setIcon(QMessageBox.Question)
        box.setText("Reset the ticked VALORANT settings files?")
        box.setInformativeText("They're backed up first. Your video settings go back to defaults (crosshair, "
                               "sensitivity and keybinds are saved by Riot online and aren't affected). Press Play "
                               "stretched afterwards and TrueStretch writes fresh files.")
        reset = box.addButton("Reset files", QMessageBox.DestructiveRole)
        box.addButton("Cancel", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is not reset:
            return
        try:
            self.engine.reset_configs(self.gid)
        except StretchError as exc:
            QMessageBox.warning(self, APP_NAME, str(exc))

    # ---- refresh ----------------------------------------------------------

    def refresh(self):
        engine, gs, info = self.engine, self.gs, self.engine.info[self.gid]
        p = palette()
        self.icon.setPixmap(game_pixmap(self.game, info, 40))
        where = str(info.install_dir) if info.installed else "Not found on this PC"
        version = info.extra.get("version") if info.installed else None     # no "version 13.10 · not found"
        self.subtitle.setText(f"{self.game.publisher}  ·  " + (f"version {version}  ·  " if version else "")
                              + where)
        state = engine.match_state(self.gid)
        if engine.running.get(self.gid) and engine.is_stretched(self.gid):
            self.status.set("In match · stretched", "accent")
        elif state == "in match":
            self.status.set("In match · native (Ctrl+Alt+S)", "warning")
        elif engine.running.get(self.gid):
            self.status.set("Menu · native", "success")
        elif engine.is_launching(self.gid):
            self.status.set("Starting…", "info")
        elif engine.is_stretched(self.gid):
            self.status.set("Stretched", "accent")
        elif not info.installed:
            self.status.set("Not found", "danger")
        else:
            self.status.set("Not running", "info")

        d = engine.display_for(self.gid)
        modes = display.available_modes(d.device if d else None)
        w, h = int(gs["width"]), int(gs["height"])
        mode = engine.stretch_mode(self.gid, modes)
        fallback = None if mode else engine.closest_mode(self.gid, modes)
        targets = engine.targets(self.gid)
        selected = engine.selected_targets(self.gid)
        mode_name = self.game.window_modes.get(gs["window_mode"], ("Fullscreen",))[0]
        target_text = str(mode) if mode else f"{w} × {h}" + (f" (or {fallback.width} × {fallback.height})"
                                                                if fallback else "")
        current = self.game.current_settings(info) if info.installed else None
        self.summary_title.setText(f"{target_text}  on  {d.title if d else 'your screen'}")
        parts = [f"{len(selected)} of {len(targets)} accounts" if targets else "accounts are set up on first Play",
                 mode_name + " + Fill",
                 "stretches when a match loads" if gs.get("auto_match", True) else "stretch with Ctrl+Alt+S"]
        if current:
            parts.append(f"in game now: FPS limit {current['fps_limit']}, VSync {'on' if current['vsync'] else 'off'}")
        self.summary_detail.setText("  ·  ".join(parts))
        running = engine.running.get(self.gid)
        for b in (self.btn_apply, self.btn_restore):
            b.setEnabled(not running and info.installed)

        checks = engine.checks(self.gid)
        bad = [c for c in checks if c.ok is not True]
        self.summary_caption.setText("Ready to play" if not bad else
                                     f"{len(bad)} thing{'s' if len(bad) > 1 else ''} to fix before you play")
        if bad:
            blocking = any(c.ok is False for c in bad)
            self.checks_icon.setPixmap(icons.pixmap("x-circle" if blocking else "alert",
                                                    p["danger" if blocking else "warning"], 18))
            self.checks_line.setText(", ".join(c.headline for c in bad[:2]) + (" …" if len(bad) > 2 else ""))
        else:
            self.checks_icon.setPixmap(icons.pixmap("check-circle", p["success"], 18))
            self.checks_line.setText(f"All {len(checks)} checks passed")
        show_grid = bool(bad) or self._checks_open
        self.checks_toggle.setText("Hide" if show_grid else "Show")
        self.checks_toggle.setVisible(not bad)
        self.btn_get.setVisible(not info.installed and self.gid in GET_GAME)
        self.checks_grid.setVisible(show_grid)
        if show_grid:
            if len(self.check_rows) != len(checks):
                self.checks_grid.clear()
                self.check_rows = [self.checks_grid.add(CheckRow()) for _ in checks]
            for row, c in zip(self.check_rows, sorted(checks, key=lambda c: c.ok is True)):
                row.set(c.headline, c.ok, c.detail)

        # stretch tab
        sizes = set(display.sizes(modes))
        native = engine.native_mode(self.gid, modes)

        def works(pw, ph):    # listed, or accepted by the driver as a custom size
            return (pw, ph) in sizes or bool(native and display.mode_accepted(
                display.Mode(pw, ph, native.hz), d.device if d else None))
        matched = False
        for tile, preset in self.tiles:
            tile.set_available(works(preset.width, preset.height))
            with quiet(tile):
                is_it = (preset.width, preset.height) == (w, h)
                tile.setChecked(is_it)
                matched = matched or is_it
        self.custom_tile.set_available(works(w, h) if not matched else None)
        if not matched:
            self.custom_tile.subtitle = f"{w} × {h}"
            with quiet(self.custom_tile):
                self.custom_tile.setChecked(True)
        else:
            self.custom_tile.subtitle = "Any size you like"
        self.custom_tile.update()
        self.custom_row.setVisible(not matched or self.custom_row.isVisible() and self.custom_tile.isChecked())
        with quiet(self.custom_w, self.custom_h):
            self.custom_w.setValue(w)
            self.custom_h.setValue(h)
        if native and w >= native.width:
            self.avail.set(f"{w} × {h} isn't narrower than your screen", False, "Nothing would stretch.")
        elif mode:
            factor = native.width / w if native else 1
            self.avail.set(f"{w} × {h} works on {d.title if d else 'your screen'}", True,
                           f"{mode.hz} Hz · players {factor:.2f}× wider")
        else:
            self.avail.set(f"{w} × {h} is created when you press Play", True,
                           "TrueStretch adds it to your graphics driver by itself"
                           + (f" — or uses {fallback.width} × {fallback.height} if the driver can't "
                              f"(players {native.width / native.height / (fallback.width / fallback.height):.2f}× "
                              "wider)." if fallback and native else "."))
        rates = display.refresh_rates(modes, w, h)
        fill_combo(self.refresh_combo,
                   [(f"Highest available ({rates[0]} Hz)" if rates else "Highest available", "max")]
                   + [(f"{r} Hz", r) for r in rates], gs.get("refresh", "max"))
        with quiet(self.mode_seg, self.auto_toggle):
            self.mode_seg.set_value(gs["window_mode"])
            self.auto_toggle.setChecked(bool(gs.get("auto_match", True)))

        tab = self.current_tab()
        if tab == "servers":
            self.servers.refresh()
        elif tab == "color":
            self.color.refresh()
        elif tab == "accounts":
            self._fill_tree(targets)
        elif tab == "display":
            self._refresh_display_tab(d, modes)
        elif tab == "launch":
            self._refresh_launch_tab(info)

    def _refresh_display_tab(self, d, modes):
        gs, engine = self.gs, self.engine
        displays = display.list_displays()
        items = [(f"Main display — {displays[0].title}" if displays else "Main display", "primary")]
        items += [(dd.label, dd.device) for dd in displays if not dd.primary]
        fill_combo(self.monitor_combo, items, gs.get("display", "primary"))
        normal_items = [("What I was using before (recommended)", "previous")]
        normal_items += [(f"{sw} × {sh}", f"{sw}x{sh}") for sw, sh in display.sizes(modes)]
        fill_combo(self.normal_combo, normal_items, gs.get("normal", "previous"))
        current = display.current_mode(d.device if d else None)
        self.desktop_now.setText(str(current) if current else "Unknown")
        with quiet(self.revert_exit, self.revert_app, self.auto_scaling_toggle):
            self.revert_exit.setChecked(bool(gs.get("revert_on_exit")))
            self.revert_app.setChecked(bool(gs.get("revert_on_app_exit")))
            self.auto_scaling_toggle.setChecked(bool(gs.get("auto_scaling", True)))
        mon = engine.monitor(self.gid)
        line = f"{d.title} (Display {d.number}) runs on {d.gpu}" if d else "Unknown"
        if mon:
            line += f"  ·  scaling now: {mon.scaling_name.lower()}"
        self.gpu_line.setText(line)

    def _refresh_launch_tab(self, info):
        gs = self.gs
        fill_combo(self.patch_combo, [(v, k) for k, v in self.game.patchlines.items()], gs.get("patchline", "live"))
        fill_combo(self.timeout_combo, [(f"{m} minutes", m) for m in (5, 10, 15, 30)],
                   gs.get("launch_timeout_min", 10))
        for tweak in self.game.tweaks(info):
            toggle = self.tweak_toggles.get(tweak.id)
            if toggle:
                with quiet(toggle):
                    toggle.setEnabled(tweak.unavailable_reason is None)
                    toggle.setToolTip(tweak.unavailable_reason or "")
                    try:
                        toggle.setChecked(bool(tweak.unavailable_reason is None and tweak.is_on()))
                    except OSError:
                        toggle.setChecked(False)
