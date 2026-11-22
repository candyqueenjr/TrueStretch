"""Reusable widgets: cards, toggles, segmented controls, tiles, badges, toasts."""

from PySide6.QtCore import (Property, QEasingCurve, QFileInfo, QPoint, QPropertyAnimation, QRectF, QSize, Qt,
                            QTimer, Signal)
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import (QAbstractButton, QButtonGroup, QFileIconProvider, QFrame, QGraphicsOpacityEffect,
                               QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget)

from . import icons
from .theme import DISPLAY_STYLES, button_font, display_font, palette


def label(text="", name=None, wrap=False, selectable=False):
    lbl = QLabel(text)
    if name:
        lbl.setObjectName(name)
        if name in DISPLAY_STYLES:                      # condensed, uppercase, tracked-out headings
            lbl.setFont(display_font(name))
    lbl.setWordWrap(wrap)
    if selectable:
        lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
    return lbl


def hbox(*items, spacing=10, margins=(0, 0, 0, 0)):
    box = QHBoxLayout()
    box.setSpacing(spacing)
    box.setContentsMargins(*margins)
    for item in items:
        _add(box, item)
    return box


def vbox(*items, spacing=10, margins=(0, 0, 0, 0)):
    box = QVBoxLayout()
    box.setSpacing(spacing)
    box.setContentsMargins(*margins)
    for item in items:
        _add(box, item)
    return box


def _add(box, item):
    if item is None:
        box.addStretch(1)
    elif isinstance(item, int):
        box.addSpacing(item)
    elif isinstance(item, QWidget):
        box.addWidget(item)
    else:
        box.addLayout(item)


def clear_layout(layout):
    """Remove everything from a layout right away (hidden now, deleted later) so nothing overlaps."""
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        if widget is not None:
            widget.hide()
            widget.setParent(None)
            widget.deleteLater()
        elif item.layout() is not None:
            clear_layout(item.layout())


def divider():
    line = QFrame()
    line.setObjectName("Divider")
    return line


def button(text, icon_name=None, kind=None, on_click=None, tooltip=None):
    btn = TacticalButton(text) if kind == "Primary" else QPushButton(text)
    if kind:
        btn.setObjectName(kind)
    if kind != "Link":
        btn.setFont(button_font())
    btn.setCursor(Qt.PointingHandCursor)
    if icon_name:
        p = palette()
        color = p["accent_text"] if kind == "Primary" else (p["danger"] if kind == "Danger" else p["muted"])
        btn.setIcon(icons.icon(icon_name, color, 16))
        btn.setIconSize(QSize(16, 16))
    if on_click:
        btn.clicked.connect(on_click)
    if tooltip:
        btn.setToolTip(tooltip)
    return btn


class TacticalButton(QPushButton):
    """The main call-to-action: a solid red block inside a thin outer frame, uppercase condensed label."""

    GAP = 4

    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self.setAttribute(Qt.WA_Hover)
        self.setMinimumHeight(44)

    def sizeHint(self):
        fm = self.fontMetrics()
        icon = self.iconSize().width() + 8 if not self.icon().isNull() else 0
        return QSize(fm.horizontalAdvance(self.text()) + icon + 44 + self.GAP * 2, 44)

    def minimumSizeHint(self):
        return self.sizeHint()

    def paintEvent(self, _event):
        p = palette()
        painter = QPainter(self)
        r = QRectF(0.5, 0.5, self.width() - 1, self.height() - 1)
        hover, down, enabled = self.underMouse(), self.isDown(), self.isEnabled()
        painter.setPen(QColor(p["text"] if hover and enabled else p["border_strong"]))
        painter.setBrush(Qt.NoBrush)
        painter.drawRect(r)
        fill = QColor(p["accent_hover"] if hover else p["accent"])
        if down:
            fill = fill.darker(112)
        if not enabled:
            fill.setAlpha(80)
        inner = r.adjusted(self.GAP, self.GAP, -self.GAP, -self.GAP)
        painter.fillRect(inner, fill)
        # small notch in the bottom-right corner - a tactical UI detail
        painter.fillRect(QRectF(inner.right() - 5, inner.bottom() - 5, 5, 5),
                         QColor(p["text"] if enabled else p["faint"]))
        painter.setFont(self.font())
        painter.setPen(QColor(p["accent_text"] if enabled else p["muted"]))
        if not self.icon().isNull():
            size = self.iconSize()
            total = size.width() + 8 + self.fontMetrics().horizontalAdvance(self.text())
            x = inner.center().x() - total / 2
            self.icon().paint(painter, int(x), int(inner.center().y() - size.height() / 2), size.width(),
                              size.height())
            painter.drawText(QRectF(x + size.width() + 8, inner.top(), total, inner.height()),
                             Qt.AlignLeft | Qt.AlignVCenter, self.text())
        else:
            painter.drawText(inner, Qt.AlignCenter, self.text())


class Card(QFrame):
    def __init__(self, padding=20, spacing=12, accent=False, parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        self.accent = accent
        self.setProperty("accent", "true" if accent else "false")
        self.body = vbox(spacing=spacing, margins=(padding, padding, padding, padding))
        self.setLayout(self.body)

    def add(self, *items):
        for item in items:
            _add(self.body, item)
        return self

    def paintEvent(self, event):
        super().paintEvent(event)
        if self.accent:                                    # corner brackets on highlighted cards
            painter = QPainter(self)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(palette()["accent"]))
            w, h, size, t = self.width(), self.height(), 14, 2
            for x, y, dx, dy in ((0, 0, 1, 1), (w, 0, -1, 1), (0, h, 1, -1), (w, h, -1, -1)):
                painter.drawRect(QRectF(x if dx > 0 else x - size, y if dy > 0 else y - t, size, t))
                painter.drawRect(QRectF(x if dx > 0 else x - t, y if dy > 0 else y - size, t, size))


class Badge(QLabel):
    def __init__(self, text="", kind="info", parent=None):
        super().__init__(text, parent)
        self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        self.setAlignment(Qt.AlignCenter)
        self.set(text, kind)

    def set(self, text, kind):
        self.setText(text)
        self.setProperty("badge", kind)
        self.style().unpolish(self)
        self.style().polish(self)


class ToggleSwitch(QAbstractButton):
    def __init__(self, checked=False, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setChecked(checked)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(40, 22)
        self._offset = 1.0 if checked else 0.0
        self._anim = QPropertyAnimation(self, b"offset", self)
        self._anim.setDuration(140)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self.toggled.connect(self._animate)

    def _animate(self, on):
        self._anim.stop()
        self._anim.setStartValue(self._offset)
        self._anim.setEndValue(1.0 if on else 0.0)
        self._anim.start()

    def setChecked(self, on):
        super().setChecked(on)
        if not self._anim_running():
            self._offset = 1.0 if on else 0.0
            self.update()

    def _anim_running(self):
        return hasattr(self, "_anim") and self._anim.state() == QPropertyAnimation.Running

    def get_offset(self):
        return self._offset

    def set_offset(self, value):
        self._offset = value
        self.update()

    offset = Property(float, get_offset, set_offset)

    def paintEvent(self, _event):
        p = palette()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        off, on = QColor(p["surface3"]), QColor(p["accent"])
        painter.setRenderHint(QPainter.Antialiasing, False)
        t = self._offset
        track = QColor(int(off.red() + (on.red() - off.red()) * t), int(off.green() + (on.green() - off.green()) * t),
                       int(off.blue() + (on.blue() - off.blue()) * t))
        if not self.isEnabled():
            track.setAlpha(90)
        painter.setPen(Qt.NoPen)
        painter.setBrush(track)
        painter.drawRect(QRectF(0, 0, self.width(), self.height()))
        knob = QColor(p["text"] if self._offset < 0.5 else "#ffffff")
        if not self.isEnabled():
            knob.setAlpha(150)
        painter.setBrush(knob)
        x = 3 + t * (self.width() - 19)
        painter.drawRect(QRectF(x, 3, 16, 16))

    def sizeHint(self):
        return QSize(40, 22)


class Segmented(QFrame):
    changed = Signal(str)

    def __init__(self, options, value=None, parent=None):
        super().__init__(parent)
        self.setObjectName("Segmented")
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.buttons = {}
        row = hbox(spacing=0, margins=(0, 0, 0, 0))
        for key, text in options:
            b = QPushButton(text)
            b.setObjectName("Segment")
            b.setFont(button_font(9.5))
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            self.group.addButton(b)
            self.buttons[key] = b
            b.clicked.connect(lambda _=False, k=key: self.changed.emit(k))
            row.addWidget(b)
        self.setLayout(row)
        self.set_value(value or options[0][0])
        self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)

    def set_value(self, key):
        if key in self.buttons:
            self.buttons[key].setChecked(True)

    def value(self):
        for key, b in self.buttons.items():
            if b.isChecked():
                return key
        return None


class SettingsGroup(Card):
    """A card of rows: title + description on the left, a control on the right."""

    def __init__(self, title=None, subtitle=None, parent=None):
        super().__init__(padding=0, spacing=0, parent=parent)
        self._rows = 0
        if title:
            head = vbox(label(title, "H2"), spacing=2, margins=(20, 16, 20, 12))
            if subtitle:
                head.addWidget(label(subtitle, "Muted", wrap=True))
            self.body.addLayout(head)
            self.body.addWidget(divider())

    def add_row(self, title, description, control=None, icon_name=None):
        if self._rows:
            self.body.addWidget(divider())
        self._rows += 1
        row = QWidget()
        row.setObjectName("Transparent")
        layout = hbox(spacing=14, margins=(20, 14, 20, 14))
        if icon_name:
            ic = QLabel()
            ic.setPixmap(icons.pixmap(icon_name, palette()["muted"], 18))
            ic.setFixedWidth(22)
            ic.setAlignment(Qt.AlignTop | Qt.AlignHCenter)
            layout.addWidget(ic)
        text = vbox(label(title, "H3"), spacing=2)
        if description:
            text.addWidget(label(description, "Muted", wrap=True))
        from .responsive import Reflow
        body = Reflow(breakpoint=620, spacing=12)       # control drops under the text on narrow windows
        body.add(text, 1)
        if control is not None:
            body.add(control, 0, Qt.AlignVCenter | Qt.AlignLeft) if isinstance(control, QWidget) else body.add(control)
        layout.addWidget(body, 1)
        row.setLayout(layout)
        self.body.addWidget(row)
        return row


class ResolutionTile(QAbstractButton):
    """A clickable card showing one stretched resolution and whether the display offers it."""

    def __init__(self, title, subtitle, note="", parent=None):
        super().__init__(parent)
        self.title, self.subtitle, self.note = title, subtitle, note
        self.available = None
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setAttribute(Qt.WA_Hover)
        self.setMinimumSize(150, 96)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def set_available(self, available):
        self.available = available
        self.update()

    def sizeHint(self):
        return QSize(170, 96)

    def paintEvent(self, _event):
        p = palette()
        painter = QPainter(self)
        rect = QRectF(0.5, 0.5, self.width() - 1, self.height() - 1)
        checked, hover = self.isChecked(), self.underMouse()
        # VALORANT-style selection: the chosen option becomes a solid off-white panel with dark text
        bg = QColor(p["text"]) if checked else QColor(p["surface2"] if not hover else p["surface3"])
        painter.setBrush(bg)
        painter.setPen(QColor(p["text"] if checked else (p["border_strong"] if hover else p["border"])))
        painter.drawRect(rect)
        if checked:
            painter.fillRect(QRectF(0, 0, self.width(), 4), QColor(p["accent"]))
        ink, sub = (QColor(p["bg"]), QColor(p["bg"])) if checked else (QColor(p["text"]), QColor(p["muted"]))
        if checked:
            sub.setAlpha(170)

        painter.setPen(ink)
        f = display_font("H2")
        f.setPointSizeF(15)
        f.setLetterSpacing(QFont.AbsoluteSpacing, 0.8)
        painter.setFont(f)
        painter.drawText(QRectF(14, 12, rect.width() - 28, 24), Qt.AlignLeft | Qt.AlignVCenter, self.title)
        f = QFont(self.font())
        f.setPointSizeF(9.5)
        painter.setFont(f)
        painter.setPen(sub)
        painter.drawText(QRectF(14, 37, rect.width() - 28, 18), Qt.AlignLeft | Qt.AlignVCenter, self.subtitle)

        if self.available is not None:
            color = QColor(("#0b8f6e" if checked else p["success"]) if self.available else
                           (p["faint"] if not checked else "#6b7480"))
            painter.setPen(Qt.NoPen)
            painter.setBrush(color)
            painter.drawRect(QRectF(14, 69, 6, 6))
            painter.setPen(color)
            painter.drawText(QRectF(27, 63, rect.width() - 40, 18), Qt.AlignLeft | Qt.AlignVCenter,
                             "Ready" if self.available else "Added when you play")
        if checked:
            painter.drawPixmap(int(rect.width() - 26), 14, icons.pixmap("check", p["accent"], 16))


class CheckRow(QWidget):
    """Icon + title + detail line, used for the 'ready to play' checklist."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Transparent")
        self.icon = QLabel()
        self.icon.setFixedSize(22, 22)
        self.title = label("", "H3")
        self.detail = label("", "Faint", wrap=True)
        self.setLayout(hbox(self.icon, vbox(self.title, self.detail, spacing=1), spacing=12))

    def set(self, title, ok, detail):
        p = palette()
        name, color = ("check-circle", p["success"]) if ok is True else (
            ("x-circle", p["danger"]) if ok is False else ("alert", p["warning"]))
        self.icon.setPixmap(icons.pixmap(name, color, 20))
        self.title.setText(title)
        self.detail.setText(detail)


class Toast(QFrame):
    """Small notification that slides in at the bottom-right of its parent and fades away."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setObjectName("Toast")
        self.icon = QLabel()
        self.text = label("", wrap=True)
        self.text.setMaximumWidth(360)
        self.setLayout(hbox(self.icon, self.text, spacing=10, margins=(14, 12, 16, 12)))
        self.effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self.effect)
        self.fade = QPropertyAnimation(self.effect, b"opacity", self)
        self.fade.setDuration(220)
        self.fade.finished.connect(self._after_fade)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self._hide)
        self.hide()

    def show_message(self, level, text):
        p = palette()
        name, color = {"success": ("check-circle", p["success"]), "warning": ("alert", p["warning"]),
                       "error": ("x-circle", p["danger"])}.get(level, ("info", p["info"]))
        self.icon.setPixmap(icons.pixmap(name, color, 20))
        self.text.setText(text)
        start = self.effect.opacity() if self.isVisible() else 0.0
        self.adjustSize()
        self.reposition()
        self.show()
        self.raise_()
        self.fade.stop()
        self.fade.setStartValue(start)
        self.fade.setEndValue(1.0)
        self.fade.start()
        self.timer.start(4500 if level in ("warning", "error") else 3200)

    def reposition(self):
        parent = self.parentWidget()
        if parent:
            self.move(QPoint(parent.width() - self.width() - 24, parent.height() - self.height() - 52))

    def _hide(self):
        self.fade.stop()
        self.fade.setStartValue(self.effect.opacity())
        self.fade.setEndValue(0.0)
        self.fade.start()

    def _after_fade(self):
        if self.fade.endValue() == 0.0:
            self.hide()


def rounded(pixmap, radius):
    out = QPixmap(pixmap.size())
    out.setDevicePixelRatio(pixmap.devicePixelRatio())
    out.fill(Qt.transparent)
    painter = QPainter(out)
    painter.setRenderHint(QPainter.Antialiasing)
    path = QPainterPath()
    w, h = pixmap.width() / pixmap.devicePixelRatio(), pixmap.height() / pixmap.devicePixelRatio()
    path.addRoundedRect(QRectF(0, 0, w, h), radius, radius)
    painter.setClipPath(path)
    painter.drawPixmap(0, 0, pixmap)
    painter.end()
    return out


def game_pixmap(game, info, size):
    """The game's own icon from its install (never bundled), or a neutral placeholder."""
    dpr = 2.0
    pm = None
    if info is not None and info.icon:
        ic = QIcon(str(info.icon))
        if not ic.isNull():
            pm = ic.pixmap(QSize(size, size), dpr)
    if (pm is None or pm.isNull()) and info is not None and info.extra.get("exe_for_icon"):
        pm = QFileIconProvider().icon(QFileInfo(str(info.extra["exe_for_icon"]))).pixmap(QSize(size, size), dpr)
    if pm is None or pm.isNull():
        p = palette()
        pm = QPixmap(int(size * dpr), int(size * dpr))
        pm.setDevicePixelRatio(dpr)
        pm.fill(QColor(p["surface3"]))
        painter = QPainter(pm)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.drawPixmap(int(size * 0.25), int(size * 0.25), icons.pixmap("gamepad", p["muted"], int(size * 0.5)))
        painter.end()
    return rounded(pm, size * 0.22)
