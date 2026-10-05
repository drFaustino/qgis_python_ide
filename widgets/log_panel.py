from __future__ import annotations

from typing import Any

from qgis.PyQt.QtCore import pyqtSignal
from qgis.PyQt.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class LogPanel(QWidget):
    """Pannello per visualizzare e filtrare i log dell'IDE."""

    filterChanged = pyqtSignal(str)

    LEVELS = ("INFO", "WARNING", "ERROR", "DEBUG")
    MAX_RECORDS = 5000

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self._records: list[tuple[str, str]] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)
        root.setSpacing(4)

        top = QHBoxLayout()
        top.setSpacing(6)

        self._title = QLabel("Log / Processi", self)
        top.addWidget(self._title)

        self.level = QComboBox(self)
        self.level.addItem("Tutti", "")
        for level in self.LEVELS:
            self.level.addItem(level, level)

        self.level.setMinimumWidth(100)

        top.addWidget(self.level)

        self.filter = QLineEdit(self)
        self.filter.setPlaceholderText("Filtra log…")
        self.filter.setClearButtonEnabled(True)
        top.addWidget(self.filter, 1)

        self.clear = QPushButton("Cancella", self)
        self.clear.setToolTip("Cancella tutti i messaggi del log")
        top.addWidget(self.clear)

        root.addLayout(top)

        self.text = QPlainTextEdit(self)
        self.text.setReadOnly(True)
        self.text.setLineWrapMode(
            QPlainTextEdit.LineWrapMode.NoWrap
        )
        self.text.setPlaceholderText(
            "I messaggi di log e i processi appariranno qui."
        )
        root.addWidget(self.text, 1)

        self.level.currentTextChanged.connect(self._apply)
        self.filter.textChanged.connect(self._on_filter_changed)
        self.clear.clicked.connect(self.clear_log)

    def retranslate(self, tr) -> None:
        """Aggiorna le etichette del pannello senza ricreare i log."""
        self._title.setText(tr("log.title", "Log / Processi"))
        self.level.setItemText(0, tr("log.all", "Tutti"))
        self.filter.setPlaceholderText(tr("log.filter", "Filtra log…"))
        self.clear.setText(tr("log.clear", "Cancella"))
        self.clear.setToolTip(tr("log.clear_tip", "Cancella tutti i messaggi del log"))
        self.text.setPlaceholderText(tr("log.placeholder", "I messaggi di log e i processi appariranno qui."))

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def append(self, message: Any, level: str = "INFO") -> None:
        """
        Aggiunge un messaggio al log.

        Il livello viene normalizzato automaticamente.
        """
        normalized_level = self._normalize_level(level)
        normalized_message = str(message)

        self._records.append(
            (normalized_level, normalized_message)
        )

        if len(self._records) > self.MAX_RECORDS:
            del self._records[
                : len(self._records) - self.MAX_RECORDS
            ]

        self._apply()

    def clear_log(self) -> None:
        """Cancella tutti i record e il contenuto visualizzato."""
        self._records.clear()
        self.text.clear()

    def records(self) -> list[tuple[str, str]]:
        """Restituisce una copia dei record memorizzati."""
        return list(self._records)

    def set_records(
        self,
        records: list[tuple[str, str]],
    ) -> None:
        """Sostituisce i record correnti."""
        normalized: list[tuple[str, str]] = []

        for level, message in records:
            normalized.append(
                (
                    self._normalize_level(level),
                    str(message),
                )
            )

        self._records = normalized[-self.MAX_RECORDS :]
        self._apply()

    # ------------------------------------------------------------------
    # Filtering
    # ------------------------------------------------------------------

    def _on_filter_changed(self, text: str) -> None:
        self.filterChanged.emit(text)
        self._apply()

    def _apply(self, *_args: Any) -> None:
        """
        Applica i filtri correnti e aggiorna il widget di testo.

        Il valore del filtro usa itemData() e quindi non dipende
        dalla lingua visualizzata nell'interfaccia.
        """
        selected_level = self.level.currentData()
        query = self.filter.text().strip().casefold()

        rows: list[str] = []

        for level, message in self._records:
            if selected_level and level != selected_level:
                continue

            if query and query not in message.casefold():
                continue

            rows.append(f"[{level}] {message}")

        scrollbar = self.text.verticalScrollBar()

        was_at_bottom = (
            scrollbar.value() >= scrollbar.maximum() - 4
        )

        self.text.setPlainText("\n".join(rows))

        if was_at_bottom:
            scrollbar.setValue(scrollbar.maximum())

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @classmethod
    def _normalize_level(cls, level: Any) -> str:
        value = str(level).strip().upper()

        if value in cls.LEVELS:
            return value

        return "INFO"
