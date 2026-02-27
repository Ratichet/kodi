from PySide6.QtWidgets import QLayout
from PySide6.QtCore import Qt, QRect, QSize, QPoint


class FlowLayout(QLayout):
    def __init__(self, parent=None, margin=0, h_spacing=12, v_spacing=12):
        super().__init__(parent)
        self._h_spacing = h_spacing
        self._v_spacing = v_spacing
        self._items = []

        if margin >= 0:
            self.setContentsMargins(margin, margin, margin, margin)

    def addItem(self, item):
        self._items.append(item)

    def horizontalSpacing(self):
        return self._h_spacing

    def verticalSpacing(self):
        return self._v_spacing

    def count(self):
        return len(self._items)

    def itemAt(self, index):
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index):
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._do_layout(QRect(0, 0, width, 0), test_only=True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do_layout(rect, test_only=False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())

        margins = self.contentsMargins()
        size += QSize(
            margins.left() + margins.right(), margins.top() + margins.bottom()
        )
        return size

    def _do_layout(self, rect, test_only=False):
        margins = self.contentsMargins()
        effective_rect = rect.adjusted(
            margins.left(), margins.top(), -margins.right(), -margins.bottom()
        )

        x = effective_rect.x()
        y = effective_rect.y()
        line_height = 0

        for item in self._items:
            widget = item.widget()
            if widget and not widget.isVisible():
                continue

            item_size = item.sizeHint()
            h_space = self._h_spacing
            v_space = self._v_spacing

            next_x = x + item_size.width() + h_space

            if next_x - h_space > effective_rect.right() and line_height > 0:
                x = effective_rect.x()
                y = y + line_height + v_space
                next_x = x + item_size.width() + h_space
                line_height = 0

            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), item_size))

            x = next_x
            line_height = max(line_height, item_size.height())

        return y + line_height - rect.y() + margins.bottom()

    def clear(self):
        while self.count():
            item = self.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
