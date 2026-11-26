"""Color tab of the VALORANT page: Game Color - vivid colours only while VALORANT is the window in front
(NVIDIA digital vibrance / AMD saturation, truestretch/gamecolor.py)."""

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QWidget

from .. import gamecolor
from .base_page import quiet
from .theme import display_font, palette
from .widgets import Badge, Card, Segmented, SettingsGroup, ToggleSwitch, button, hbox, label, vbox

# Colours a player looks for in a round: enemy highlight, abilities, map accents, skin tones, shadows.
SWATCHES = ["#c8463c", "#d9b648", "#5aa66e", "#3f8fb0", "#8a5fb5", "#c98f6b", "#6d7b86"]


def _boost(hex_color, percent):
    """Roughly what the driver does: push the saturation up (digital vibrance is a saturation curve)."""
    c = QColor(hex_color)
    h, s, v, _ = c.getHsvF()
    s = min(1.0, s * (1.0 + 0.9 * percent / 100.0))
    v = min(1.0, v * (1.0 + 0.08 * percent / 100.0))
    return QColor.fromHsvF(max(h, 0.0), s, v)


class ColorPreview(QWidget):
    """Two strips of the same colours: your screen now, and in VALORANT at the chosen strength."""

    def __init__(self):
        super().__init__()
        self.percent = 50
        self.active = True
        self.setMinimumHeight(118)

    def sizeHint(self):
        return QSize(520, 118)

    def set_percent(self, percent, active=True):
        self.percent, self.active = percent, active
        self.update()

    def paintEvent(self, event):
        p = palette()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        caption = display_font("Caption")
        painter.setFont(caption)
        label_w = 110
        rows = [("YOUR DESKTOP", 0), ("IN VALORANT", self.percent if self.active else 0)]
        gap, row_h = 6, 44
        y = 4
        for text, pct in rows:
            painter.setPen(QColor(p["muted"]))
            painter.drawText(QRectF(0, y, label_w - 10, row_h), Qt.AlignVCenter | Qt.AlignLeft, text)
            avail = self.width() - label_w
            w = (avail - gap * (len(SWATCHES) - 1)) / len(SWATCHES)
            for i, sw in enumerate(SWATCHES):
                painter.setPen(Qt.NoPen)
                painter.setBrush(_boost(sw, pct))
                painter.drawRect(QRectF(label_w + i * (w + gap), y, w, row_h))
            y += row_h + 14
        painter.end()


class ColorTab(QWidget):
    def __init__(self, engine, gid, window):
        super().__init__()
        self.setObjectName("Transparent")
        self.engine, self.gid, self.window = engine, gid, window
        self.screen = None
        layout = vbox(spacing=16, margins=(0, 0, 0, 0))
        self.setLayout(layout)

        self.state = Badge("", "info")
        intro = label("Brighter, more saturated colours make enemy outlines and abilities easier to spot. Game "
                      "Color turns them on only while VALORANT is the window in front — alt-tab and your desktop, "
                      "videos and other apps look normal again at once.", "Muted", wrap=True)
        self.preview = ColorPreview()
        self.screen_line = label("", "Muted", wrap=True)
        head = hbox(label("Game Color", "H1"), self.state, None, spacing=12)
        layout.addWidget(Card().add(head, intro, self.preview, self.screen_line))

        group = SettingsGroup("Settings")
        self.toggle = ToggleSwitch()
        self.toggle.toggled.connect(lambda on: self._changed(enabled=on))
        group.add_row("Vivid colours in VALORANT", "Turns on when VALORANT is in front, off when it isn't, and "
                      "always off when the game or TrueStretch closes.", self.toggle, "sparkle")
        self.level = Segmented([(k, t) for k, t, _ in gamecolor.LEVELS], "medium")
        self.level.changed.connect(lambda k: self._changed(level=k))
        group.add_row("Strength", None, self.level, "sliders")
        self.try_btn = button("Preview 4 s", "play", None, self._preview,
                              "Shows the chosen strength on your desktop for 4 seconds")
        group.add_row("Try it", "See the strength on your desktop for 4 seconds before you play.", self.try_btn,
                      "monitor")
        layout.addWidget(group)
        layout.addWidget(label("Fair play: this is the same screen setting NVIDIA Control Panel (Digital vibrance) "
                               "and AMD Software (Saturation) offer. Nothing reads or changes the game, its files "
                               "or Vanguard.", "Faint", wrap=True))

    def _changed(self, enabled=None, level=None):
        self.engine.set_color(enabled=enabled, level=level, gid=self.gid)
        self.refresh(rescan=False)

    def _preview(self):
        if not self.engine.preview_color(self.gid):
            self.window.toast.show_message("info", "Close VALORANT first — while it runs, Game Color follows the "
                                                   "game window.")

    def refresh(self, rescan=True):
        if rescan or self.screen is None:
            self.screen, self.reason = self.engine.color_screen(self.gid)
        enabled, percent = self.engine.color_settings(self.gid)
        gs = self.engine.gs(self.gid)
        with quiet(self.toggle, self.level):
            self.toggle.setChecked(enabled)
            self.level.set_value(gs.get("game_color_level", "medium"))
        s = self.screen
        supported = s is not None
        running = bool(self.engine.running.get(self.gid))
        self.toggle.setEnabled(supported or enabled)        # can always be switched off
        self.level.setEnabled(supported)
        self.try_btn.setEnabled(supported and not running)
        self.try_btn.setToolTip("Close VALORANT to preview" if running else
                                "Shows the chosen strength on your desktop for 4 seconds")
        self.preview.set_percent(percent, enabled and supported)
        if supported:
            target = s.target(percent)
            self.screen_line.setText(f"Your screen: {s.vendor} {s.setting} — normal {s.shown(s.level)}, "
                                     f"in VALORANT {s.shown(target)}.")
            self.level.setToolTip(f"{s.vendor} {s.setting} in game: {s.shown(target)}")
        else:
            self.screen_line.setText(self.reason or "Not available on this screen.")
        if not supported:
            self.state.set("Not available here", "warning")
        elif self.engine.color_active():
            self.state.set("On now", "success")
        elif enabled:
            self.state.set("Ready — turns on in game", "info")
        else:
            self.state.set("Off", "info")
