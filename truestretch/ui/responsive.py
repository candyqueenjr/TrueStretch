"""Layouts that adapt to the window width: a grid that changes its number of columns, and a row that stacks
vertically when there isn't room. Used everywhere content would otherwise squash or clip."""

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import QBoxLayout, QGridLayout, QSizePolicy, QWidget


class ResponsiveGrid(QWidget):
    """Lays its widgets out in as many columns as fit (each at least `min_width` wide, at most `max_cols`)."""

    def __init__(self, min_width=220, max_cols=4, spacing=12, parent=None):
        super().__init__(parent)
        self.setObjectName("Transparent")
        self.min_width, self.max_cols = min_width, max_cols
        self.items = []
        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(spacing)
        self._cols = 0
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)

    def add(self, widget):
        self.items.append(widget)
        self._cols = 0
        self._relayout(self.width() or self.min_width * self.max_cols)
        return widget

    def clear(self):
        for w in self.items:
            self.grid.removeWidget(w)
            w.setParent(None)
            w.deleteLater()
        self.items = []
        self._cols = 0

    def columns_for(self, width):
        spacing = self.grid.horizontalSpacing()
        cols = max(1, min(self.max_cols, (width + spacing) // (self.min_width + spacing)))
        cols = min(cols, max(1, len(self.items)))
        while cols > 2 and len(self.items) % cols == 1:     # no lonely last item: 4 cards -> 2x2, not 3+1
            cols -= 1
        return cols

    def _relayout(self, width):
        cols = self.columns_for(width)
        if cols == self._cols:
            return
        self._cols = cols
        for w in self.items:
            self.grid.removeWidget(w)
        for i in range(self.grid.columnCount()):
            self.grid.setColumnStretch(i, 0)
        for i, w in enumerate(self.items):
            self.grid.addWidget(w, i // cols, i % cols)
        for i in range(cols):
            self.grid.setColumnStretch(i, 1)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._relayout(event.size().width())

    def minimumSizeHint(self):
        # Never demand more than one column's width - otherwise the grid could never get narrow enough to reflow.
        hint = self.grid.minimumSize()
        return QSize(min(hint.width(), self.min_width), hint.height())


class Reflow(QWidget):
    """A row of widgets/layouts that becomes a column below `breakpoint` pixels (e.g. title + buttons)."""

    def __init__(self, breakpoint=760, spacing=12, parent=None):
        super().__init__(parent)
        self.setObjectName("Transparent")
        self.breakpoint = breakpoint
        self.box = QBoxLayout(QBoxLayout.LeftToRight, self)
        self.box.setContentsMargins(0, 0, 0, 0)
        self.box.setSpacing(spacing)
        self._stretch_items = []

    def add(self, item, stretch=0, align=Qt.Alignment()):
        if isinstance(item, QWidget):
            self.box.addWidget(item, stretch, align)
        elif item is None:
            self.box.addStretch(1)
        else:
            self.box.addLayout(item, stretch)
        return self

    def resizeEvent(self, event):
        super().resizeEvent(event)
        vertical = event.size().width() < self.breakpoint
        want = QBoxLayout.TopToBottom if vertical else QBoxLayout.LeftToRight
        if self.box.direction() != want:
            self.box.setDirection(want)

    def minimumSizeHint(self):
        # In a row, the minimum width would be the sum of everything - which would stop the row from ever getting
        # narrow enough to stack. Ask only for the widest single item; the row stacks below the breakpoint.
        widest = 0
        for i in range(self.box.count()):
            it = self.box.itemAt(i)
            widest = max(widest, it.minimumSize().width())
        return QSize(min(widest, self.breakpoint), self.box.minimumSize().height())
