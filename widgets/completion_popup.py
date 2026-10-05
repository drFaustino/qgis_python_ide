from __future__ import annotations

from typing import Any, Callable, Iterable

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QFont
from qgis.PyQt.QtWidgets import (
    QFrame,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
)


class CompletionPopup(QFrame):
    """Popup per la selezione dei suggerimenti di completamento."""

    def __init__(
        self,
        parent: Any,
        items: Iterable[Any],
        insert_callback: Callable[[Any], None],
    ) -> None:
        super().__init__(
            parent,
            Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint,
        )

        self.insert_callback = insert_callback

        self.setObjectName("CompletionPopup")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setMinimumWidth(360)
        self.setMaximumHeight(420)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)

        self.list = QListWidget(self)
        self.list.setObjectName("CompletionList")
        self.list.setFont(QFont(parent.font()))
        self.list.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self.list.setVerticalScrollMode(
            QListWidget.ScrollMode.ScrollPerItem
        )
        self.list.setSelectionMode(
            QListWidget.SelectionMode.SingleSelection
        )

        layout.addWidget(self.list)

        self._populate(items)

        self.list.itemActivated.connect(self._pick)
        self.list.itemClicked.connect(self._pick)

        if self.list.count() > 0:
            self.list.setCurrentRow(0)
            self.list.setFocus()

    # ------------------------------------------------------------------
    # Population
    # ------------------------------------------------------------------

    def _populate(self, items: Iterable[Any]) -> None:
        """Popola la lista dei suggerimenti."""
        self.list.clear()

        for item in items:
            name = self._item_name(item)
            type_name = self._item_type(item)

            if type_name:
                label = f"{name}    {type_name}"
            else:
                label = name

            list_item = QListWidgetItem(label)
            list_item.setData(
                Qt.ItemDataRole.UserRole,
                item,
            )

            self.list.addItem(list_item)

    @staticmethod
    def _item_name(item: Any) -> str:
        """Estrae il nome visualizzato dell'elemento."""
        value = getattr(item, "name", None)

        if value is None:
            value = str(item)

        return str(value)

    @staticmethod
    def _item_type(item: Any) -> str:
        """Estrae il tipo dell'elemento, se disponibile."""
        value = getattr(item, "type_name", None)

        if value is None:
            value = getattr(item, "kind", None)

        if value is None:
            return ""

        text = str(value).strip()

        if text.lower() in {"none", "null"}:
            return ""

        return text

    # ------------------------------------------------------------------
    # Selection
    # ------------------------------------------------------------------

    def _pick(self, item: QListWidgetItem | None) -> None:
        """Inserisce il suggerimento selezionato."""
        if item is None:
            return

        value = item.data(Qt.ItemDataRole.UserRole)

        if value is None:
            return

        self.insert_callback(value)
        self.close()

    # ------------------------------------------------------------------
    # Keyboard
    # ------------------------------------------------------------------

    def keyPressEvent(self, event) -> None:
        """Gestisce i tasti principali del popup."""
        key = event.key()

        if key in (
            Qt.Key.Key_Return,
            Qt.Key.Key_Enter,
            Qt.Key.Key_Tab,
        ):
            current = self.list.currentItem()

            if current is not None:
                self._pick(current)

            event.accept()
            return

        if key == Qt.Key.Key_Escape:
            self.close()
            event.accept()
            return

        if key == Qt.Key.Key_Up:
            current = self.list.currentRow()

            if current > 0:
                self.list.setCurrentRow(current - 1)

            event.accept()
            return

        if key == Qt.Key.Key_Down:
            current = self.list.currentRow()
            last = self.list.count() - 1

            if current < last:
                self.list.setCurrentRow(current + 1)

            event.accept()
            return

        super().keyPressEvent(event)
