"""First-launch tour: explains stretched res, scans the PC step by step, explains what it found,
and lets the player pick a resolution."""

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QButtonGroup, QDialog, QGridLayout, QLabel, QStackedWidget, QWidget

from .. import APP_NAME, display, health
from . import icons
from .theme import palette
from .widgets import ResolutionTile, button, clear_layout, game_pixmap, hbox, label, vbox


def _page():
    w = QWidget()
    w.setObjectName("Transparent")
    layout = vbox(spacing=14)
    w.setLayout(layout)
    return w, layout


class WelcomeDialog(QDialog):
    def __init__(self, engine, window):
        super().__init__(window)
        self.engine, self.window = engine, window
        self.gid = next(iter(engine.games))
        self.setWindowTitle(f"Welcome to {APP_NAME}")
        self.setWindowFlag(Qt.WindowContextHelpButtonHint, False)
        self.setModal(True)
        self.resize(760, 600)

        self.stack = QStackedWidget()
        self.dots = hbox(spacing=6)
        self.back = button("Back", None, "Ghost", self._back)
        self.next = button("Next", None, "Primary", self._next)
        self.next.setMinimumWidth(150)
        footer = hbox(self.dots, None, self.back, self.next, spacing=8)
        self.setLayout(vbox(self.stack, footer, spacing=18, margins=(32, 28, 32, 24)))

        self._build_intro()
        self._build_scan()
        self._build_results()
        self._build_pick()
        self._build_done()
        self._go(0)

    # ---- pages ------------------------------------------------------------

    def _build_intro(self):
        page, layout = _page()
        logo = QLabel()
        logo.setPixmap(self.window.logo_pixmap(72))
        layout.addWidget(logo)
        layout.addWidget(label(f"Welcome to {APP_NAME}", "PageTitle"))
        layout.addWidget(label("True stretched resolution makes VALORANT render at a 4:3 resolution like 1440 × 1080 "
                               "and stretches it across your whole screen. Characters look wider, and many players "
                               "find it easier to aim. Normally that takes four guides and a lot of fiddling.",
                               "Muted", wrap=True))
        steps = [("search", "We look at your PC", "Game, accounts, screens, graphics card and Windows settings."),
                 ("check", "We explain what we found", "In plain words, with a fix for anything that's not right."),
                 ("play", "You press Play", "Everything is switched for you, and switched back when you're done.")]
        for icon_name, title, text in steps:
            ic = QLabel()
            ic.setPixmap(icons.pixmap({"search": "pulse"}.get(icon_name, icon_name), palette()["accent"], 22))
            ic.setFixedWidth(28)
            row = hbox(ic, spacing=12)
            row.addLayout(vbox(label(title, "H3"), label(text, "Muted", wrap=True), spacing=2), 1)
            layout.addLayout(row)
        layout.addWidget(label("Nothing is changed until you press Play stretched, and every file is backed up first.",
                               "Faint", wrap=True))
        layout.addStretch(1)
        self.stack.addWidget(page)

    def _build_scan(self):
        page, layout = _page()
        layout.addWidget(label("Looking at your PC…", "H1"))
        layout.addWidget(label("This only reads information. Nothing is changed.", "Muted"))
        self.scan_rows = []
        for text in ("Looking for VALORANT", "Finding your accounts", "Checking your screens",
                     "Checking your graphics card", "Checking monitor drivers", "Checking Windows gaming settings",
                     "Checking anti-cheat"):
            ic = QLabel()
            ic.setFixedSize(22, 22)
            title = label(text, "H3")
            detail = label("", "Faint", wrap=True)
            row = hbox(ic, spacing=12)
            row.addLayout(vbox(title, detail, spacing=1), 1)
            layout.addLayout(row)
            self.scan_rows.append((ic, title, detail))
        layout.addStretch(1)
        self.stack.addWidget(page)
        self.scan_timer = QTimer(self)
        self.scan_timer.timeout.connect(self._scan_step)

    def _build_results(self):
        page, layout = _page()
        layout.addWidget(label("Here's what we found", "H1"))
        self.results = vbox(spacing=12)
        layout.addLayout(self.results)
        layout.addStretch(1)
        self.stack.addWidget(page)

    def _build_pick(self):
        page, layout = _page()
        layout.addWidget(label("Pick your stretched resolution", "H1"))
        layout.addWidget(label("1440 × 1080 is what most pros use. You can change this any time.", "Muted",
                               wrap=True))
        grid = QGridLayout()
        grid.setSpacing(10)
        self.tile_group = QButtonGroup(self)
        self.tiles = []
        game = self.engine.games[self.gid]
        for i, preset in enumerate(game.presets):
            tile = ResolutionTile(f"{preset.width} × {preset.height}", f"{preset.aspect} · {preset.note}")
            tile.clicked.connect(lambda _=False, p=preset: self._pick(p.width, p.height))
            self.tile_group.addButton(tile)
            self.tiles.append((tile, preset))
            grid.addWidget(tile, i // 3, i % 3)
        layout.addLayout(grid)
        self.pick_note = label("", "Muted", wrap=True)
        layout.addWidget(self.pick_note)
        layout.addStretch(1)
        self.stack.addWidget(page)

    def _build_done(self):
        page, layout = _page()
        ic = QLabel()
        ic.setPixmap(icons.pixmap("check-circle", palette()["success"], 56))
        layout.addWidget(ic)
        layout.addWidget(label("You're all set", "PageTitle"))
        self.done_text = label("", "Muted", wrap=True)
        layout.addWidget(self.done_text)
        tips = [
            "Press Play stretched on the Home page. TrueStretch switches everything and starts VALORANT.",
            "When you close VALORANT, your normal resolution comes back by itself.",
            "My PC shows everything about your PC, with fixes. Settings lets you change anything.",
            "TrueStretch keeps running in the tray (next to the clock) so it can switch back after you play.",
        ]
        for tip in tips:
            dot = QLabel("•")
            dot.setFixedWidth(12)
            row = hbox(dot, spacing=6)
            row.addWidget(label(tip, "Muted", wrap=True), 1)
            layout.addLayout(row)
        layout.addStretch(1)
        self.stack.addWidget(page)

    # ---- behaviour --------------------------------------------------------

    def _go(self, index):
        self.stack.setCurrentIndex(index)
        clear_layout(self.dots)
        p = palette()
        for i in range(self.stack.count()):
            dot = QLabel()
            dot.setFixedSize(22 if i == index else 8, 8)
            dot.setStyleSheet(f"background:{p['accent'] if i == index else p['surface3']}; border-radius:0;")
            self.dots.addWidget(dot)
        self.back.setVisible(index >= 3)
        self.next.setText({0: "Scan my PC", 1: "Scanning…", 3: "Use this", 4: "Start using TrueStretch"}
                          .get(index, "Next"))
        self.next.setEnabled(index != 1)
        if index == 1:
            self._start_scan()
        elif index == 2:
            self._fill_results()
        elif index == 3:
            self._fill_pick()
        elif index == 4:
            self._fill_done()

    def _next(self):
        if self.stack.currentIndex() == self.stack.count() - 1:
            self.accept()
        else:
            self._go(self.stack.currentIndex() + 1)

    def _back(self):
        self._go(self.stack.currentIndex() - 1)

    def _start_scan(self):
        self.engine.refresh(quiet=True)
        engine, gid = self.engine, self.gid
        info, pc = engine.info[gid], engine.pc
        targets = engine.targets(gid)
        displays = display.list_displays()
        accounts = sum(1 for t in targets if not t.is_default)
        screens = ", ".join(d.title for d in displays) or "none found"
        gpu = pc.gpus[0] if pc.gpus else None
        devs = [dev for _, dev in engine.monitor_devices() if dev]
        off = sum(1 for dev in devs if dev.disabled)
        self.scan_results = [
            (info.installed, f"Found in {info.install_dir}" if info.installed else "Not found on this PC"),
            (bool(targets), f"{accounts} account{'s' if accounts != 1 else ''} on this PC" if targets
             else "None yet — set up after your first session"),
            (bool(displays), screens),
            (gpu is not None, f"{gpu.name} · driver {gpu.friendly_driver}" if gpu else "Unknown"),
            (bool(devs) and off == len(devs),
             "All off — VALORANT can't read the 16:9 shape (needed)" if devs and off == len(devs) else
             f"{len(devs) - off} still on — Play stretched turns them off for you (one admin prompt)"),
            (True, f"{pc.windows} · Game Mode {'on' if pc.game_mode else 'off'} · "
                   f"power: {pc.power_mode or pc.power_plan or 'default'}"),
            (pc.vanguard_installed, "Vanguard is " + ("running" if pc.vanguard_running else
                                                      "installed" if pc.vanguard_installed else "not installed")),
        ]
        p = palette()
        for ic, title, detail in self.scan_rows:
            ic.setPixmap(icons.pixmap("clock", p["faint"], 20))
            title.setStyleSheet(f"color:{p['faint']};")
            detail.setText("")
        self.scan_index = 0
        self.scan_timer.start(380)

    def _scan_step(self):
        p = palette()
        if self.scan_index >= len(self.scan_rows):
            self.scan_timer.stop()
            self.next.setEnabled(True)
            self.next.setText("See results")
            return
        ic, title, detail = self.scan_rows[self.scan_index]
        ok, text = self.scan_results[self.scan_index]
        ic.setPixmap(icons.pixmap("check-circle" if ok else "alert", p["success"] if ok else p["warning"], 20))
        title.setStyleSheet("")
        detail.setText(text)
        self.scan_index += 1

    def _fill_results(self):
        clear_layout(self.results)
        engine, gid = self.engine, self.gid
        p = palette()
        info, pc = engine.info[gid], engine.pc
        game = engine.games[gid]
        items = health.checks(engine, gid)
        counts = health.summary(items)

        row = hbox(spacing=14)
        gi = QLabel()
        gi.setPixmap(game_pixmap(game, info, 48))
        version = info.extra.get("version")
        row.addWidget(gi)
        row.addLayout(vbox(label(game.name + (f" {version}" if version else ""), "H2"),
                           label(str(info.install_dir) if info.installed else "Not installed", "Muted"), spacing=2), 1)
        self.results.addLayout(row)

        d = engine.display_for(gid)
        sentences = []
        displays = display.list_displays()
        if len(displays) > 1:
            sentences.append(f"You have {len(displays)} screens. VALORANT plays on your main one: {d.title}.")
        elif d:
            sentences.append(f"Your screen is {d.title}.")
        if pc.gpus:
            sentences.append(f"Your graphics card is the {pc.gpus[0].name}"
                             + (f", and there's also an {pc.gpus[1].name} built in." if len(pc.gpus) > 1 else "."))
        if pc.laptop:
            sentences.append("This is a laptop" + (", running on battery right now — plug it in to play."
                                                   if pc.on_battery else ", plugged in."))
        current = game.current_settings(info) if info.installed else None
        if current:
            sentences.append(f"VALORANT is currently on {current['mode']} + "
                             f"{'Fill' if current['fill'] else 'Letterbox'}"
                             + (" — ready." if current["ready"] else
                                ". Play stretched switches it to Windowed fullscreen + Fill."))
        for s in sentences:
            self.results.addWidget(label(s, "Muted", wrap=True))

        problems = [i for i in items if i.status in (health.WARN, health.BAD)]
        if problems:
            self.results.addSpacing(6)
            self.results.addWidget(label(f"{len(problems)} thing{'s' if len(problems) > 1 else ''} to look at", "H3"))
            for item in problems[:4]:
                ic = QLabel()
                ic.setPixmap(icons.pixmap("x-circle" if item.status == health.BAD else "alert",
                                          p["danger"] if item.status == health.BAD else p["warning"], 18))
                ic.setFixedWidth(22)
                r = hbox(ic, spacing=10)
                r.addWidget(label(item.title, None, wrap=True), 1)
                self.results.addLayout(r)
            self.results.addWidget(label("You can fix these with one click on the My PC page.", "Faint"))
        else:
            self.results.addWidget(label(f"Everything looks good — {counts[health.GOOD]} checks passed.", "H3"))

    def _fill_pick(self):
        gs = self.engine.gs(self.gid)
        d = self.engine.display_for(self.gid)
        sizes = set(display.sizes(display.available_modes(d.device if d else None)))
        for tile, preset in self.tiles:
            tile.set_available((preset.width, preset.height) in sizes)
            tile.setChecked((preset.width, preset.height) == (int(gs["width"]), int(gs["height"])))
        self._update_pick_note()

    def _pick(self, w, h):
        gs = self.engine.gs(self.gid)
        gs["width"], gs["height"], gs["refresh"] = w, h, "max"
        self.engine.save()
        self._update_pick_note()

    def _update_pick_note(self):
        gs = self.engine.gs(self.gid)
        mode = self.engine.stretch_mode(self.gid)
        w, h = gs["width"], gs["height"]
        if mode:
            self.pick_note.setText(f"✔  {w} × {h} is ready on your screen at up to {mode.hz} Hz.")
        else:
            fallback = self.engine.closest_mode(self.gid)
            self.pick_note.setText(f"✔  TrueStretch adds {w} × {h} to your graphics driver when you play"
                                   + (f" (or uses {fallback.width} × {fallback.height} if the driver can't)."
                                      if fallback else "."))

    def _fill_done(self):
        mode = self.engine.stretch_mode(self.gid)
        gs = self.engine.gs(self.gid)
        self.done_text.setText(f"All set. Close this and press Play stretched — TrueStretch does the rest "
                               f"({gs['width']} × {gs['height']}{'' if mode else ', added automatically'}).")
