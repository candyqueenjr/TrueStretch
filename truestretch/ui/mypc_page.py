"""My PC: hardware, screens and a plain-language health check with one-click fixes."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QGuiApplication
from PySide6.QtWidgets import QGridLayout, QLabel, QListWidget, QListWidgetItem, QWidget

from .. import APP_NAME, VERSION, display, displayconfig, health
from ..paths import DATA_DIR, LOG_DIR, log
from ..system import open_path
from . import icons
from .base_page import Page
from .theme import palette
from .widgets import Badge, Card, button, clear_layout, divider, hbox, label, vbox

SCALING_WORDS = {1: "none", 2: "centred (black bars)", 3: "stretched to full screen",
                 4: "keeps the aspect ratio (black bars)", 5: "custom", 128: "driver default"}
STATUS_ICON = {health.GOOD: ("check-circle", "success"), health.WARN: ("alert", "warning"),
               health.BAD: ("x-circle", "danger"), health.INFO: ("info", "info")}


class HardwareCard(Card):
    def __init__(self, icon_name, caption):
        super().__init__(padding=16, spacing=4)
        self.icon_name = icon_name
        self.icon = QLabel()
        self.value = label("", "H3", wrap=True)
        self.sub = label("", "Faint", wrap=True)
        self.add(hbox(self.icon, label(caption.upper(), "Caption"), None, spacing=8), 4, self.value, self.sub)
        self.body.addStretch(1)

    def set(self, value, sub=""):
        self.icon.setPixmap(icons.pixmap(self.icon_name, palette()["accent"], 18))
        self.value.setText(value)
        self.sub.setText(sub)
        self.sub.setVisible(bool(sub))


class HealthRow(QWidget):
    def __init__(self, item, on_fix):
        super().__init__()
        self.setObjectName("Transparent")
        p = palette()
        name, color = STATUS_ICON[item.status]
        ic = QLabel()
        ic.setPixmap(icons.pixmap(name, p[color], 20))
        ic.setFixedWidth(24)
        ic.setAlignment(Qt.AlignTop | Qt.AlignHCenter)
        text = vbox(label(item.title, "H3", wrap=True), label(item.detail, "Muted", wrap=True), spacing=3)
        row = hbox(ic, spacing=14, margins=(20, 14, 20, 14))
        row.addLayout(text, 1)
        if item.fix:
            kind = "Primary" if item.status in (health.WARN, health.BAD) else None
            row.addWidget(button(item.fix_label, None, kind, lambda: on_fix(item)), 0, Qt.AlignVCenter)
        self.setLayout(row)


class MyPcPage(Page):
    def __init__(self, engine, window, game_id):
        super().__init__(engine, window)
        self.gid = game_id
        self.add_header("My PC", "Everything TrueStretch found on this PC, explained. Anything that isn't green "
                        "comes with a fix.",
                        hbox(button("Scan again", "refresh", None, lambda: self.engine.refresh()),
                             button("Copy report", "copy", None, self._copy), spacing=8))

        self.summary = Card(padding=20)
        self.summary_icon = QLabel()
        self.summary_title = label("", "H2")
        self.summary_detail = label("", "Muted", wrap=True)
        self.summary_badges = hbox(spacing=6)
        text = vbox(self.summary_title, self.summary_detail, self.summary_badges, spacing=6)
        row = hbox(self.summary_icon, spacing=16)
        row.addLayout(text, 1)
        self.summary.add(row)
        self.content.addWidget(self.summary)

        from .responsive import ResponsiveGrid
        grid = ResponsiveGrid(min_width=230, max_cols=4, spacing=12)
        self.hw = {
            "cpu": HardwareCard("sliders", "Processor"),
            "gpu": HardwareCard("monitor", "Graphics"),
            "ram": HardwareCard("archive", "Memory"),
            "os": HardwareCard("shield", "System"),
        }
        for card in self.hw.values():
            grid.add(card)
        self.content.addWidget(grid)

        self.screens = Card(padding=0, spacing=0)
        self.content.addWidget(self.screens)
        self.health_box = vbox(spacing=18)
        self.content.addLayout(self.health_box)

        self.tech = Card()
        self.content.addWidget(self.tech)
        activity = Card()
        self.activity = QListWidget()
        self.activity.setMinimumHeight(200)
        activity.add(hbox(label("Activity", "H2"), None,
                          button("Open log folder", "folder", "Ghost", lambda: open_path(LOG_DIR))),
                     self.activity)
        self.content.addWidget(activity)
        self.finish()
        self.refresh()

    # ---- refresh ----------------------------------------------------------

    def refresh(self):
        engine, pc = self.engine, self.engine.pc
        p = palette()
        items = health.checks(engine, self.gid)
        counts = health.summary(items)

        # summary
        clear_layout(self.summary_badges)
        if counts[health.BAD]:
            icon, color = "x-circle", "danger"
            title = f"{counts[health.BAD]} thing{'s' if counts[health.BAD] > 1 else ''} to fix before stretched res works"
        elif counts[health.WARN]:
            icon, color = "alert", "warning"
            title = f"Ready to play — {counts[health.WARN]} thing{'s' if counts[health.WARN] > 1 else ''} could be better"
        else:
            icon, color = "check-circle", "success"
            title = "Everything looks great"
        self.summary_icon.setPixmap(icons.pixmap(icon, p[color], 40))
        self.summary_title.setText(title)
        when = pc.scanned_at.strftime("%H:%M") if pc.scanned_at else "just now"
        self.summary_detail.setText(f"TrueStretch checked your game, screens, graphics and Windows settings "
                                    f"(last scan {when}). Use the buttons next to anything yellow or red.")
        for status, text, kind in ((health.GOOD, "good", "success"), (health.WARN, "to improve", "warning"),
                                   (health.BAD, "to fix", "danger"), (health.INFO, "tips", "info")):
            if counts[status]:
                self.summary_badges.addWidget(Badge(f"{counts[status]} {text}", kind))
        self.summary_badges.addStretch(1)

        # hardware
        self.hw["cpu"].set(pc.cpu.replace("(R)", "").replace("(TM)", "") or "Unknown",
                           f"{pc.cores} threads" if pc.cores else "")
        if pc.gpus:
            main = pc.gpus[0]
            sub = f"Driver {main.friendly_driver}" + (f" · {main.vram_gb:g} GB" if main.vram_gb else "")
            if len(pc.gpus) > 1:
                sub += f"\nAlso: {', '.join(g.name for g in pc.gpus[1:])}"
            self.hw["gpu"].set(main.name, sub)
        else:
            self.hw["gpu"].set("Unknown")
        self.hw["ram"].set(f"{round(pc.ram_gb)} GB" if pc.ram_gb else "Unknown",
                           "Laptop" + (f" · battery {pc.battery_percent}%" if pc.battery_percent is not None else "")
                           if pc.laptop else "Desktop PC")
        self.hw["os"].set(pc.windows, f"Power: {pc.power_mode or pc.power_plan or 'default'}")

        # screens - read, then shown row by row; if a display read fails halfway (a screen reconnecting, a driver
        # reset) the card says so instead of being left empty, and the rest of the page still refreshes.
        clear_layout(self.screens.body)
        self.screens.body.addLayout(vbox(label("Your screens", "H2"),
                                         label("What each screen is, what it can do and which graphics card "
                                               "drives it.", "Muted"), spacing=2, margins=(20, 16, 20, 12)))
        try:
            self._add_screen_rows(p)
        except Exception:
            log.exception("Reading the screens failed")
            clear_layout(self.screens.body)
            self.screens.body.addLayout(vbox(label("Your screens", "H2"), margins=(20, 16, 20, 12)))
            self.screens.body.addWidget(divider())
            self.screens.body.addLayout(hbox(label("Couldn't read your screens just now — press Scan again.",
                                                   "Muted", wrap=True), margins=(20, 14, 20, 14)))

        # health
        clear_layout(self.health_box)
        groups = []
        for item in items:
            if item.group not in groups:
                groups.append(item.group)
        for group in groups:
            card = Card(padding=0, spacing=0)
            card.body.addLayout(vbox(label(group, "H2"), margins=(20, 16, 20, 12)))
            for item in (i for i in items if i.group == group):
                card.body.addWidget(divider())
                card.body.addWidget(HealthRow(item, self.window.run_fix))
            self.health_box.addWidget(card)

        # technical details + activity
        clear_layout(self.tech.body)
        self.tech.add(label("Technical details", "H2"))
        grid = QGridLayout()
        grid.setHorizontalSpacing(24)
        grid.setVerticalSpacing(8)
        grid.setColumnStretch(1, 1)
        for row_i, (key, value) in enumerate(self._facts()):
            grid.addWidget(label(key, "Muted"), row_i, 0, Qt.AlignTop)
            grid.addWidget(label(value, "Mono", selectable=True), row_i, 1)
        self.tech.body.addLayout(grid)

        self.activity.clear()
        colors = {"success": p["success"], "warning": p["warning"], "error": p["danger"], "info": p["muted"]}
        for when, level, text in reversed(engine.history[-200:]):
            item = QListWidgetItem(f"{when:%H:%M:%S}   {text}")
            item.setForeground(QColor(colors.get(level, p["muted"])))
            self.activity.addItem(item)

    def _add_screen_rows(self, p):
        """One row per screen, added to the screens card as it's read."""
        engine = self.engine
        used = engine.display_for(self.gid)
        mons = {m.device: m for m in displayconfig.monitors()}
        drivers = {m.device: dev for m, dev in engine.monitor_devices()}
        for d in display.list_displays():
            modes = display.available_modes(d.device)
            cur = display.current_mode(d.device)
            native = d.native or (cur.size if cur else None)
            rates = display.refresh_rates(modes, *native) if native else []
            mon = mons.get(d.device)
            ic = QLabel()
            ic.setPixmap(icons.pixmap("monitor", p["muted"], 26))
            badges = hbox(spacing=6)
            if d.primary:
                badges.addWidget(Badge("Main display", "info"))
            if used and used.device == d.device:
                badges.addWidget(Badge("Used for VALORANT", "accent"))
            badges.addStretch(1)
            scaling = SCALING_WORDS.get(mon.scaling, mon.scaling_name.lower()) if mon else None
            driver = drivers.get(d.device)
            facts = [f"{native[0]} × {native[1]}" + (f" up to {rates[0]} Hz" if rates else "") if native else None,
                     f"now {cur}" if cur else None,
                     f"Windows scaling: {scaling}" if scaling else None,
                     ("monitor driver off (good for stretched res)" if driver.disabled else
                      "monitor driver on (Play turns it off)") if driver else None,
                     f"{mon.connection}" if mon and not mon.built_in else None,
                     f"on the {d.gpu}" if d.gpu else None]
            text = vbox(hbox(label(d.title, "H3"), label(f"Display {d.number}", "Faint"), None, spacing=8),
                        label("  ·  ".join(f for f in facts if f), "Muted", wrap=True), badges, spacing=4)
            row = hbox(ic, spacing=16, margins=(20, 14, 20, 14))
            row.addLayout(text, 1)
            holder = QWidget()
            holder.setObjectName("Transparent")
            holder.setLayout(row)
            self.screens.body.addWidget(divider())
            self.screens.body.addWidget(holder)

    def _facts(self):
        engine = self.engine
        info = engine.info[self.gid]
        last = info.extra.get("last_signed_in")
        return [
            ("App", f"{APP_NAME} {VERSION}"),
            ("Game folder", str(info.install_dir) if info.install_dir else "not found"),
            ("Found via", info.found_via or "—"),
            ("Game program", str(info.game_exe) if info.game_exe else "not found"),
            ("Riot Client", str(info.launcher) if info.launcher else "not found"),
            ("Settings folder", str(info.config_root) if info.config_root else "not found"),
            ("Game version", info.extra.get("version") or "—"),
            ("Region", info.region or "—"),
            ("Last signed in", f"account {last[:8]}" if last else "—"),
            ("TrueStretch data", str(DATA_DIR)),
            ("Stretched now", f"yes, since {engine.state.data.get('since')}" if engine.state.stretched else "no"),
        ]

    def _copy(self):
        pc = self.engine.pc
        lines = [f"{APP_NAME} PC report", "", f"Windows: {pc.windows}", f"CPU: {pc.cpu} ({pc.cores} threads)",
                 f"Memory: {pc.ram_gb:g} GB", f"Laptop: {'yes' if pc.laptop else 'no'}",
                 f"Power: {pc.power_mode or pc.power_plan}", f"Game Mode: {'on' if pc.game_mode else 'off'}"]
        lines += [f"GPU: {g.name}, driver {g.friendly_driver} ({g.driver_date})" for g in pc.gpus]
        for d in display.list_displays():
            lines.append(f"{d.label}: {display.current_mode(d.device)}")
        lines += [""] + [f"{k}: {v}" for k, v in self._facts()]
        lines += ["", "[Checks]"] + [f"{i.status.upper():5} {i.title}" for i in health.checks(self.engine, self.gid)]
        lines += ["", "[Recent activity]"] + [f"{w:%H:%M:%S} {lvl}: {t}" for w, lvl, t in self.engine.history[-30:]]
        QGuiApplication.clipboard().setText("\n".join(lines))
        self.engine.notify("success", "PC report copied to the clipboard.")
