from contextlib import contextmanager

from PySide6.QtCore import QSignalBlocker, Qt
from PySide6.QtWidgets import QComboBox, QScrollArea, QWidget

from .widgets import hbox, label, vbox


@contextmanager
def quiet(*widgets):
    """Update controls from settings without firing their change handlers."""
    blockers = [QSignalBlocker(w) for w in widgets]
    try:
        yield
    finally:
        for b in blockers:
            b.unblock()


def fill_combo(combo: QComboBox, items, current):
    """items: [(text, data)]. Keeps the selection on `current` if present."""
    with quiet(combo):
        combo.clear()
        for text, data in items:
            combo.addItem(text, data)
        index = combo.findData(current)
        combo.setCurrentIndex(index if index >= 0 else 0)


MAX_WIDTH = 1240


class Page(QScrollArea):
    """A scrolling page whose content sits in a centred column (max 1240 px) with margins that shrink on small
    windows - so it never squashes on a laptop and never stretches into long lines on a wide monitor."""

    def __init__(self, engine, window):
        super().__init__()
        self.engine, self.window = engine, window
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        outer = QWidget()
        outer.setObjectName("Transparent")
        column = QWidget()
        column.setObjectName("Transparent")
        column.setMaximumWidth(MAX_WIDTH)
        self.content = vbox(spacing=18, margins=(40, 30, 40, 36))
        column.setLayout(self.content)
        row = hbox(spacing=0)
        row.addStretch(1)
        row.addWidget(column, 100)
        row.addStretch(1)
        outer.setLayout(row)
        self.setWidget(outer)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        w = event.size().width()
        side = 40 if w >= 1100 else 26 if w >= 820 else 16
        m = self.content.contentsMargins()
        if m.left() != side:
            self.content.setContentsMargins(side, 30 if w >= 820 else 20, side, 36)

    def add_header(self, title, subtitle=None, right=None, eyebrow=None):
        text = vbox(spacing=4)
        if eyebrow:
            text.addWidget(label(eyebrow, "Eyebrow"))
        text.addWidget(label(title, "PageTitle"))
        if subtitle:
            text.addWidget(label(subtitle, "Muted", wrap=True))
        row = hbox(spacing=12)
        row.addLayout(text, 1)
        if right is not None:
            row.addLayout(right) if not isinstance(right, QWidget) else row.addWidget(right, 0, Qt.AlignTop)
        self.content.addLayout(row)
        self.content.addSpacing(4)

    def finish(self):
        self.content.addStretch(1)

    def refresh(self):
        pass
