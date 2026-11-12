"""The per-game page: everything for one game, in tabs."""

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QAbstractItemView, QButtonGroup, QComboBox, QHeaderView, QLabel,
                               QMessageBox, QSpinBox, QTabWidget, QTreeWidget, QTreeWidgetItem, QWidget)

from .. import display
from ..display import installed_gpus
from ..engine import StretchError
from ..guides import GUIDES, open_display_settings
from ..system import open_path
from . import icons
from .base_page import Page, fill_combo, quiet
from .theme import palette
from .responsive import Reflow, ResponsiveGrid
from .widgets import (Badge, Card, CheckRow, ResolutionTile, Segmented, SettingsGroup, ToggleSwitch, button,
                      clear_layout, divider, game_pixmap, hbox, label, vbox)


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
        self._build_header()
        self._build_action_card()
        self.tabs = QTabWidget()
        from .theme import button_font
        self.tabs.tabBar().setFont(button_font(10.5, spacing=1.6))
        self.tabs.setDocumentMode(True)
        self.content.addWidget(self.tabs)
        self._build_resolution_tab()
        self._build_accounts_tab()
        self._build_display_tab()
        self._build_launch_tab()
        self._build_guide_tab()
        self.tabs.removeTab(4)          # setup is automatic now; the guide stays reachable from code, not in the flow
        self.finish()
        self.refresh()

    @property
    def gs(self):
        return self.engine.gs(self.gid)

    def _set(self, key, value):
        self.gs[key] = value
        self.engine.save()

    # ---- header & actions -------------------------------------------------

    def _build_header(self):
        from ..games import COMING_SOON
        self.icon = QLabel()
        self.icon.setFixedSize(64, 64)
        self.title = label(self.game.name, "PageTitle")
        self.subtitle = label("", "Muted")
        self.subtitle.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.subtitle.setWordWrap(True)
        self.status = Badge("", "info")
        rescan = button("Rescan", "refresh", "Ghost", lambda: self.engine.refresh())
        rescan.setToolTip("Look for the game, its settings files and your displays again")
        soon = label("More games soon: " + " · ".join(g.name for g in COMING_SOON), "Caption")
        text = vbox(label("// True stretched", "Eyebrow"), hbox(self.title, self.status, None, spacing=14),
                    self.subtitle, spacing=2)
        row = hbox(self.icon, spacing=18)
        row.addLayout(text, 1)
        row.addWidget(rescan, 0, Qt.AlignTop)
        self.content.addLayout(row)
        self.content.addWidget(soon)

    def _build_action_card(self):
        card = Card(padding=20, accent=True)
        self.summary_title = label("", "H2")
        self.summary_title.setWordWrap(True)
        self.summary_detail = label("", "Muted")
        self.summary_detail.setWordWrap(True)
        self.btn_restore = button("Restore normal", "undo", "Ghost", lambda: self.window.restore(self.gid),
                                  "Put back your original game settings and normal desktop resolution")
        self.btn_apply = button("Test stretch", "monitor", None, lambda: self.window.test_stretch(self.gid),
                                "Stretch the desktop for 15 seconds so you can see whether your screen fills")
        top = Reflow(breakpoint=720, spacing=10)
        top.add(vbox(label("Ready to play", "Caption"), self.summary_title, self.summary_detail, spacing=3), 1)
        top.add(hbox(self.btn_restore, self.btn_apply, spacing=8))
        self.checks_grid = ResponsiveGrid(min_width=290, max_cols=3, spacing=14)
        self.check_rows = []
        card.add(top, divider(), self.checks_grid)
        self.content.addWidget(card)

    # ---- tab: resolution --------------------------------------------------

    def show_tab(self, name):
        names = {"resolution": 0, "accounts": 1, "display": 2, "launch": 3, "guide": 0}
        self.tabs.setCurrentIndex(names.get(name, 0))

    def _build_resolution_tab(self):
        page, layout = tab_page()
        self.now_card = Card(padding=16)
        self.now_icon = QLabel()
        self.now_title = label("", "H3")
        self.now_detail = label("", "Muted", wrap=True)
        row = hbox(self.now_icon, spacing=14)
        row.addLayout(vbox(self.now_title, self.now_detail, spacing=2), 1)
        self.now_card.add(row)
        layout.addWidget(self.now_card)
        card = Card()
        card.add(label("Stretched resolution", "H2"),
                 label("The size your desktop switches to once a match has loaded — narrower means wider models. "
                       "Change it live in a match with Ctrl+Alt+↑ (more) and Ctrl+Alt+↓ (less).", "Muted",
                       wrap=True))
        grid = ResponsiveGrid(min_width=180, max_cols=5, spacing=10)
        self.tile_group = QButtonGroup(self)
        self.tiles = []
        for i, preset in enumerate(self.game.presets):
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
        self.btn_guide = button("How to create it", "book", "Link", lambda: self.tabs.setCurrentIndex(4))
        card.add(hbox(self.avail, None, self.btn_guide,
                      button("Re-check display", "refresh", "Ghost", self.refresh), spacing=8))
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
                     "— that's what the 2026 method needs.", self.mode_seg, "stretch")
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

    def _build_accounts_tab(self):
        page, layout = tab_page()
        card = Card()
        card.add(label("Settings files", "H2"),
                 label("VALORANT keeps a separate settings file for every account that has signed in on this PC, "
                       "plus a default one for new accounts. Ticked files get stretched. Double-click a name to "
                       "give it a nickname.", "Muted", wrap=True))
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Name", "Last played", "Current setting", "Locked"])
        self.tree.setRootIsDecorated(False)
        self.tree.setAlternatingRowColors(False)
        self.tree.setSelectionMode(QAbstractItemView.SingleSelection)
        self.tree.setEditTriggers(QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed)
        self.tree.setMinimumHeight(220)
        header = self.tree.header()
        header.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        for col, width in ((1, 150), (2, 200), (3, 80)):
            header.setSectionResizeMode(col, QHeaderView.Fixed)
            header.resizeSection(col, width)
        self.tree.itemChanged.connect(self._tree_changed)
        card.add(self.tree)
        card.add(hbox(button("Select all", None, None, lambda: self._select_all(True)),
                      button("Select none", None, None, lambda: self._select_all(False)),
                      None,
                      button("Reset settings files", "trash", "Danger", self._reset_files,
                             "Delete the ticked files (backed up first) so VALORANT starts clean — fixes a "
                             "greyed-out Fill option"),
                      button("Open settings folder", "folder", "Ghost",
                             lambda: open_path(self.engine.info[self.gid].config_root or ".")),
                      spacing=8))
        layout.addWidget(card)
        layout.addStretch(1)
        self.tabs.addTab(page, "Accounts")

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
        nickname = item.text(0).replace("  •  last signed in", "").strip()
        default_label = item.data(0, Qt.UserRole + 1)
        nicknames = self.gs.setdefault("nicknames", {})
        if nickname and nickname != default_label:
            nicknames[key] = nickname
        else:
            nicknames.pop(key, None)
        self.engine.save()

    def _select_all(self, on):
        keys = [t.key for t in self.engine.targets(self.gid)]
        self.gs["excluded"] = [] if on else keys
        self.engine.save()

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
        layout.addWidget(Card().add(hbox(
            label("Need to change scaling or create resolutions?", "Muted"), None,
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
        launch.add_row("Server", "Which VALORANT the Riot Client starts.", self.patch_combo, "gamepad")
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

    # ---- tab: setup guide -------------------------------------------------

    def _reset_files(self):
        answer = QMessageBox.question(
            self, "TrueStretch", "Reset the ticked VALORANT settings files?\n\nThey're backed up first. Your video "
            "settings go back to defaults (crosshair, sensitivity and keybinds are saved by Riot online and aren't "
            "affected). Press Play stretched afterwards and TrueStretch writes fresh files.")
        if answer != QMessageBox.Yes:
            return
        try:
            self.engine.reset_configs(self.gid)
        except StretchError as exc:
            QMessageBox.warning(self, "TrueStretch", str(exc))

    def _monitor_drivers(self, enabled):
        try:
            self.engine.set_monitor_drivers(enabled, int(self.window.winId()))
        except StretchError as exc:
            QMessageBox.warning(self, "TrueStretch", str(exc))

    def _build_method_card(self, layout):
        card = Card(padding=0, spacing=0)
        head = vbox(label("True stretched checklist", "H2"),
                    label("Tested in game on VALORANT 13.08. TrueStretch checks each step and does it for you where "
                          "Windows allows it.", "Muted", wrap=True), spacing=2, margins=(20, 16, 20, 12))
        card.body.addLayout(head)
        self.method_rows = vbox(spacing=0)
        card.body.addLayout(self.method_rows)
        layout.addWidget(card)

    def _method_row(self, number, title, status, detail, actions):
        p = palette()
        num = QLabel(str(number))
        num.setFixedSize(26, 26)
        num.setAlignment(Qt.AlignCenter)
        color = {"ok": p["success"], "todo": p["warning"], "auto": p["info"]}[status]
        num.setStyleSheet(f"background:{color}; color:#0d0f13; border-radius:0; font-weight:700;")
        state = {"ok": "Done", "todo": "To do", "auto": "Automatic"}[status]
        text = vbox(hbox(label(title, "H3"), Badge(state, {"ok": "success", "todo": "warning",
                                                           "auto": "info"}[status]), None, spacing=8),
                    label(detail, "Muted", wrap=True), spacing=3)
        row = hbox(num, spacing=14, margins=(20, 14, 20, 14))
        row.setAlignment(num, Qt.AlignTop)
        row.addLayout(text, 1)
        for text_, kind, fn in actions:
            # run after the click finishes: the action refreshes this card and deletes the button
            row.addWidget(button(text_, None, kind, lambda _=False, f=fn: QTimer.singleShot(0, f)), 0,
                          Qt.AlignVCenter)
        holder = QWidget()
        holder.setObjectName("Transparent")
        holder.setLayout(row)
        self.method_rows.addWidget(divider())
        self.method_rows.addWidget(holder)

    def _render_method(self):
        engine, gs, gid = self.engine, self.gs, self.gid
        key = None
        pairs = engine.monitor_devices()
        devs = [dev for _, dev in pairs if dev]
        disabled = [dev for dev in devs if dev.disabled]
        mode = engine.stretch_mode(gid)
        mon = engine.monitor(gid)
        current = self.game.current_settings(engine.info[gid]) if engine.info[gid].installed else None
        w, h = gs["width"], gs["height"]
        key = (len(devs), len(disabled), bool(mode), mon.scaling if mon else None, gs.get("auto_match"),
               current["ready"] if current else None, w, h, engine.running.get(gid))
        if getattr(self, "_method_key", None) == key:
            return
        self._method_key = key
        clear_layout(self.method_rows)

        if mode:
            self._method_row(1, f"Custom resolution {w} × {h}", "ok",
                             f"Your driver accepts it at {mode.hz} Hz.", [])
        else:
            fallback = engine.closest_mode(gid)
            self._method_row(1, f"Custom resolution {w} × {h}", "auto",
                             "Play stretched adds it to your graphics driver (NVIDIA, AMD or Intel) by itself."
                             + (f" If the driver refuses, TrueStretch uses {fallback.width} × {fallback.height} "
                                "instead — nothing to do by hand." if fallback else ""), [])

        self._method_row(2, "GPU scaling: Full-screen", "ok" if mon and mon.stretches else "auto",
                         "TrueStretch sets the graphics driver to Full-screen / Full panel / Stretch when you press "
                         "Play, and asks Windows to stretch again whenever a match stretches.", [])

        if devs and not disabled:
            self._method_row(3, "Monitor drivers off before launch", "todo",
                             "VALORANT reads your monitor's real 16:9 shape and squeezes the stretch back unless the "
                             "monitors are disabled in Device Manager. Safe — your screens keep working.",
                             [("Turn off (admin)", "Primary", lambda: self._monitor_drivers(False))])
        else:
            self._method_row(3, "Monitor drivers off before launch", "ok",
                             "Disabled in Device Manager, so VALORANT can't read the 16:9 shape.",
                             [("Turn back on", "Ghost", lambda: self._monitor_drivers(True))])

        self._method_row(4, "In game: Windowed fullscreen + Fill", "ok" if current and current["ready"] else "auto",
                         "Written to VALORANT's settings when you press Play (backed up first). VALORANT then follows "
                         "the desktop when it switches mid-match.", [("Reset files", None, self._reset_files)])

        self._method_row(5, "Stretch only after the match has loaded", "ok" if gs.get("auto_match", True) else "todo",
                         "Native in menus, agent select and loading; stretched the moment the map is ready; native "
                         "again in the menu. Switching earlier gives black bars. Ctrl+Alt+S does it by hand.", [])

    def _build_trouble_card(self, layout):
        card = Card(padding=0, spacing=0)
        card.body.addLayout(vbox(label("Troubleshooting", "H2"), margins=(20, 16, 20, 12)))
        problems = [
            ("Black bars at the left and right",
             "That's the graphics driver keeping the aspect ratio: set Full-screen (NVIDIA) / Full panel (AMD) / "
             "Stretch (Intel) as shown below. Press Test stretch to check without opening the game.",
             ("Test stretch", lambda: self.window.test_stretch(self.gid))),
            ("Black bars at the top and bottom in a match",
             "VALORANT is letterboxing: the desktop switched too early or the monitor drivers are on. Press "
             "Ctrl+Alt+S twice (native, then stretched again) once the round has started.", None),
            ("Picture fills the screen but models look normal",
             "The stretch was applied before the match loaded (VALORANT then squeezes it back). Press Ctrl+Alt+S "
             "twice in the round, or leave auto-stretch on so it switches at the right moment.", None),
            ("I want more (or less) stretch",
             "In a match press Ctrl+Alt+↑ for more and Ctrl+Alt+↓ for less — it switches instantly and remembers "
             "your choice.", None),
            ("Black bars only on the loading screen",
             "Normal — the stretch starts when the map has loaded.", None),
            ("Picture looks blurry",
             "Keep the same height as your screen (1080 on a 1080p screen) — all stretch levels do.", None),
            ("My screen went black after switching",
             "Wait — it switches back by itself after the countdown. You can also press Restore normal.", None),
        ]
        for title, text, action in problems:
            card.body.addWidget(divider())
            row = hbox(spacing=14, margins=(20, 12, 20, 12))
            row.addLayout(vbox(label(title, "H3"), label(text, "Muted", wrap=True), spacing=2), 1)
            if action:
                row.addWidget(button(action[0], None, None, action[1]), 0, Qt.AlignVCenter)
            holder = QWidget()
            holder.setObjectName("Transparent")
            holder.setLayout(row)
            card.body.addWidget(holder)
        layout.addWidget(card)

    def _build_guide_tab(self):
        page, layout = tab_page()
        self._build_method_card(layout)
        intro = Card()
        self.gpu_line = label("", "H3", wrap=True)
        self.gpu_other = label("", "Muted", wrap=True)
        intro.add(label("One-time graphics setup", "H2"),
                  label("Windows can only use a stretched resolution once your graphics driver offers it and "
                        "stretches it to the full screen. Do these steps once — TrueStretch handles everything "
                        "else.", "Muted", wrap=True),
                  self.gpu_line, self.gpu_other)
        layout.addWidget(intro)

        self.vendor_seg = Segmented([("nvidia", "NVIDIA"), ("amd", "AMD"), ("intel", "Intel")])
        self.vendor_seg.changed.connect(lambda _: self._render_guide())
        self.guide_card = Card()
        self.guide_title = label("", "H2")
        self.guide_open = button("Open", "external", "Primary", self._open_vendor_panel)
        self.guide_steps = vbox(spacing=14)
        self.guide_card.add(hbox(self.guide_title, None, self.vendor_seg, self.guide_open, spacing=10),
                            self.guide_steps)
        layout.addWidget(self.guide_card)

        confirm = SettingsGroup()
        self.auto_scaling_toggle = ToggleSwitch()
        self.auto_scaling_toggle.toggled.connect(lambda on: self._set("auto_scaling", on))
        confirm.add_row("Set stretch scaling automatically",
                        "When you press Play, TrueStretch asks Windows to stretch the picture to the full screen "
                        "(no black bars) and puts your setting back afterwards. Works on most NVIDIA, AMD and Intel "
                        "drivers — if you still see black bars, turn this off and use the steps above.",
                        self.auto_scaling_toggle, "wand")
        self.scaling_toggle = ToggleSwitch()
        self.scaling_toggle.toggled.connect(lambda on: self._set("gpu_scaling_confirmed", on))
        confirm.add_row("I've set GPU scaling to full-screen / stretch",
                        "TrueStretch can't read this setting from your driver, so confirm it once. If you still see "
                        "black bars in game, this is the step to check.", self.scaling_toggle, "check-circle")
        layout.addWidget(confirm)
        self._build_trouble_card(layout)
        layout.addStretch(1)
        self.tabs.addTab(page, "Setup guide")
        self._vendor_initialized = False

    def _render_guide(self):
        vendor = self.vendor_seg.value() or "nvidia"
        w, h = self.gs["width"], self.gs["height"]
        key = (vendor, w, h, palette()["dark"])
        if getattr(self, "_guide_key", None) == key:
            return
        self._guide_key = key
        guide = GUIDES[vendor]
        self.guide_title.setText(guide["title"])
        self.guide_open.setText(f"Open {guide['title'].split(':')[0]}")
        clear_layout(self.guide_steps)
        p = palette()
        for i, (title, detail) in enumerate(guide["steps"], 1):
            num = QLabel(str(i))
            num.setFixedSize(26, 26)
            num.setAlignment(Qt.AlignCenter)
            num.setStyleSheet(f"background:{p['surface3']}; border-radius:0; font-weight:700;")
            row = QWidget()
            row.setObjectName("Transparent")
            row.setLayout(hbox(num, vbox(label(title, "H3"), label(detail.format(w=w, h=h), "Muted", wrap=True),
                                         spacing=2), spacing=14))
            row.layout().setAlignment(num, Qt.AlignTop)
            self.guide_steps.addWidget(row)

    def _open_vendor_panel(self):
        try:
            GUIDES[self.vendor_seg.value() or "nvidia"]["open"]()
        except OSError as exc:
            self.engine.notify("warning", str(exc))

    # ---- refresh ----------------------------------------------------------

    def refresh(self):
        engine, gs, info = self.engine, self.gs, self.engine.info[self.gid]
        p = palette()
        self.icon.setPixmap(game_pixmap(self.game, info, 60))
        where = str(info.install_dir) if info.installed else "Not found on this PC"
        version = info.extra.get("version")
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
        self.summary_title.setText(f"{target_text}  on  {d.title if d else 'your screen'}")
        self.summary_detail.setText("  ·  ".join([
            f"{len(selected)} of {len(targets)} accounts",
            mode_name + " + Fill",
            "stretches when a match loads" if gs.get("auto_match", True) else "stretch with Ctrl+Alt+S",
        ]))
        running = engine.running.get(self.gid)
        for b in (self.btn_apply, self.btn_restore):
            b.setEnabled(not running)
        checks = engine.checks(self.gid)
        if len(self.check_rows) != len(checks):
            self.checks_grid.clear()
            self.check_rows = [self.checks_grid.add(CheckRow()) for _ in checks]
        for row, c in zip(self.check_rows, checks):
            row.set(c.title, c.ok, c.detail)

        # resolution tab
        current = self.game.current_settings(info) if info.installed else None
        self.now_card.setVisible(current is not None)
        if current:
            ready = current["ready"]
            self.now_icon.setPixmap(icons.pixmap("check-circle" if ready else "info",
                                                 p["success"] if ready else p["info"], 22))
            who = engine.target_name(self.gid, current["account"])
            state = ("Windowed fullscreen + Fill — ready" if ready else
                     f"{current['mode']} + {'Fill' if current['fill'] else 'Letterbox'} — Play stretched sets "
                     "Windowed fullscreen + Fill")
            self.now_title.setText(f"In VALORANT right now: {state}")
            self.now_detail.setText(f"{current['mode']} · FPS limit {current['fps_limit']} · VSync "
                                    f"{'on' if current['vsync'] else 'off'} · {who}")
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
                           f"{mode.hz} Hz · models {factor:.2f}× wider")
        else:
            self.avail.set(f"{w} × {h} is added when you play", True,
                           "TrueStretch adds it to your graphics driver by itself"
                           + (f" — or uses {fallback.width} × {fallback.height} if the driver can't "
                              f"(models {native.width / native.height / (fallback.width / fallback.height):.2f}× "
                              "wider)." if fallback and native else "."))
        self.btn_guide.setVisible(False)
        rates = display.refresh_rates(modes, w, h)
        fill_combo(self.refresh_combo,
                   [(f"Highest available ({rates[0]} Hz)" if rates else "Highest available", "max")]
                   + [(f"{r} Hz", r) for r in rates], gs.get("refresh", "max"))
        with quiet(self.mode_seg, self.auto_toggle):
            self.mode_seg.set_value(gs["window_mode"])
            self.auto_toggle.setChecked(bool(gs.get("auto_match", True)))

        # accounts tab
        with quiet(self.tree):
            self.tree.clear()
            excluded = set(gs.get("excluded", []))
            for t in targets:
                name = engine.target_name(self.gid, t)
                item = QTreeWidgetItem([name + ("  •  last signed in" if t.last_signed_in else ""),
                                        t.last_used.strftime("%d %b %Y, %H:%M"), t.current,
                                        "Yes" if t.read_only else "No"])
                item.setData(0, Qt.UserRole, t.key)
                item.setData(0, Qt.UserRole + 1, t.label)
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsEditable)
                item.setCheckState(0, Qt.Unchecked if t.key in excluded else Qt.Checked)
                item.setIcon(0, icons.icon("user" if not t.is_default else "sparkle", p["muted"], 16))
                item.setToolTip(0, str(t.path))
                self.tree.addTopLevelItem(item)
            if not targets:
                item = QTreeWidgetItem(["No settings files yet — press Play stretched; they're set up after your first session", "", "", ""])
                item.setFlags(Qt.NoItemFlags)
                self.tree.addTopLevelItem(item)

        # display tab
        displays = display.list_displays()
        items = [(f"Main display — {displays[0].title}" if displays else "Main display", "primary")]
        items += [(dd.label, dd.device) for dd in displays if not dd.primary]
        fill_combo(self.monitor_combo, items, gs.get("display", "primary"))
        normal_items = [("What I was using before (recommended)", "previous")]
        normal_items += [(f"{sw} × {sh}", f"{sw}x{sh}") for sw, sh in display.sizes(modes)]
        fill_combo(self.normal_combo, normal_items, gs.get("normal", "previous"))
        current = display.current_mode(d.device if d else None)
        self.desktop_now.setText(str(current) if current else "Unknown")
        with quiet(self.revert_exit, self.revert_app):
            self.revert_exit.setChecked(bool(gs.get("revert_on_exit")))
            self.revert_app.setChecked(bool(gs.get("revert_on_app_exit")))

        # launch tab
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

        # guide tab
        vendor = d.vendor if d else "other"
        gpus = installed_gpus()
        self.gpu_line.setText(f"Display {d.number if d else 1} runs on: {d.gpu if d else 'unknown'}")
        others = [g for g in gpus if not d or g != d.gpu]
        self.gpu_other.setText(("Also in this PC: " + ", ".join(others) + ". On laptops the built-in screen usually "
                                "runs on the Intel/AMD chip, external monitors on the NVIDIA card.") if others else "")
        self.gpu_other.setVisible(bool(others))
        if not self._vendor_initialized:
            self.vendor_seg.set_value(vendor if vendor in GUIDES else "nvidia")
            self._vendor_initialized = True
        self._render_guide()
        self._render_method()
        with quiet(self.scaling_toggle, self.auto_scaling_toggle):
            self.scaling_toggle.setChecked(bool(gs.get("gpu_scaling_confirmed")))
            self.auto_scaling_toggle.setChecked(bool(gs.get("auto_scaling", True)))
        mon = engine.monitor(self.gid)
        if mon:
            self.gpu_line.setText(f"{d.title} (Display {d.number}) runs on: {d.gpu}  ·  "
                                  f"scaling now: {mon.scaling_name.lower()}")
