from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, Iterable

from qgis.PyQt.QtCore import pyqtSignal

from qgis.PyQt.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


@dataclass
class SearchOptions:
    case_sensitive: bool = False
    whole_word: bool = False
    regex: bool = False


class FindReplacePanel(QWidget):
    """Pannello dockabile professionale per trova/sostituisci."""

    searchRequested = pyqtSignal(str, object)
    replaceRequested = pyqtSignal(str, str, object)
    replaceAllRequested = pyqtSignal(str, str, object)
    navigateRequested = pyqtSignal(str, bool, object)

    def __init__(
        self,
        document_provider: Callable[[], Iterable[object]],
        current_document_provider: Callable[[], object | None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)

        self._document_provider = document_provider
        self._current_document_provider = current_document_provider
        self._tr = lambda key, default: default

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(7)

        form = QFormLayout()
        form.setHorizontalSpacing(8)
        form.setVerticalSpacing(6)

        self.find_label = QLabel("Trova", self)

        self.find_edit = QLineEdit(self)
        self.find_edit.setClearButtonEnabled(True)
        self.find_edit.returnPressed.connect(self._find_next)
        form.addRow(self.find_label, self.find_edit)

        self.replace_label = QLabel("Sostituisci con", self)

        self.replace_edit = QLineEdit(self)
        self.replace_edit.setClearButtonEnabled(True)
        self.replace_edit.returnPressed.connect(self._replace)
        form.addRow(self.replace_label, self.replace_edit)

        root.addLayout(form)

        options = QHBoxLayout()
        options.setSpacing(10)

        self.case_check = QCheckBox("Maiuscole/minuscole", self)
        self.whole_check = QCheckBox("Parola intera", self)
        self.regex_check = QCheckBox("Regex", self)

        options.addWidget(self.case_check)
        options.addWidget(self.whole_check)
        options.addWidget(self.regex_check)
        options.addStretch(1)

        root.addLayout(options)

        scope_row = QHBoxLayout()
        scope_row.setSpacing(6)

        self.scope_label = QLabel("Ambito", self)
        self.scope = QComboBox(self)
        self.scope.addItem("Documento corrente", "current")
        self.scope.addItem("Tutti i documenti", "all")

        scope_row.addWidget(self.scope_label)
        scope_row.addWidget(self.scope, 1)

        root.addLayout(scope_row)

        navigation = QHBoxLayout()
        navigation.setSpacing(6)

        self.previous_button = QPushButton("Precedente", self)
        self.next_button = QPushButton("Successivo", self)
        self.replace_button = QPushButton("Sostituisci", self)
        self.replace_all_button = QPushButton("Sostituisci tutto", self)

        navigation.addWidget(self.previous_button)
        navigation.addWidget(self.next_button)
        navigation.addWidget(self.replace_button)
        navigation.addWidget(self.replace_all_button)

        root.addLayout(navigation)

        self.result_label = QLabel("", self)
        self.result_label.setWordWrap(True)
        root.addWidget(self.result_label)

        root.addStretch(1)

        self.previous_button.clicked.connect(self._find_previous)
        self.next_button.clicked.connect(self._find_next)
        self.replace_button.clicked.connect(self._replace)
        self.replace_all_button.clicked.connect(self._replace_all)

        self.find_edit.textChanged.connect(self._update_count)
        self.case_check.toggled.connect(self._update_count)
        self.whole_check.toggled.connect(self._update_count)
        self.regex_check.toggled.connect(self._update_count)
        self.scope.currentIndexChanged.connect(self._update_count)

        self.setMinimumWidth(340)

    # ------------------------------------------------------------------
    # Translation
    # ------------------------------------------------------------------

    def retranslate(self, tr) -> None:
        self._tr = tr

        self.find_label.setText(
            tr("ui.find", "Trova")
        )

        self.replace_label.setText(
            tr("ui.replace_with_label", "Sostituisci con")
        )

        self.find_edit.setPlaceholderText(
            tr("ui.find_current", "Cerca nel documento…")
        )
        self.replace_edit.setPlaceholderText(
            tr("ui.replace_with", "Sostituisci con…")
        )

        self.case_check.setText(
            tr("ui.case_sensitive", "Maiuscole/minuscole")
        )
        self.whole_check.setText(
            tr("ui.whole_word", "Parola intera")
        )
        self.regex_check.setText(
            tr("ui.regex", "Regex")
        )

        self.scope_label.setText(
            tr("ui.scope", "Ambito")
        )

        self.scope.setItemText(
            0,
            tr("ui.current_document", "Documento corrente"),
        )
        self.scope.setItemText(
            1,
            tr("ui.all_documents", "Tutti i documenti"),
        )

        self.previous_button.setText(
            tr("ui.find_previous", "Precedente")
        )
        self.next_button.setText(
            tr("ui.find_next", "Successivo")
        )
        self.replace_button.setText(
            tr("ui.replace", "Sostituisci")
        )
        self.replace_all_button.setText(
            tr("ui.replace_all", "Sostituisci tutto")
        )

        self._update_count()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def focus_search(self) -> None:
        self.show()
        self.raise_()
        self.find_edit.setFocus()
        self.find_edit.selectAll()

    def options(self) -> SearchOptions:
        return SearchOptions(
            case_sensitive=self.case_check.isChecked(),
            whole_word=self.whole_check.isChecked(),
            regex=self.regex_check.isChecked(),
        )

    def scope_value(self) -> str:
        value = self.scope.currentData()
        if value in ("current", "all"):
            return str(value)
        return "current"

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def _find_next(self) -> None:
        query = self.find_edit.text()
        if not query:
            self._set_result(0)
            return

        self.navigateRequested.emit(
            query,
            True,
            self._search_payload(),
        )

    def _find_previous(self) -> None:
        query = self.find_edit.text()
        if not query:
            self._set_result(0)
            return

        self.navigateRequested.emit(
            query,
            False,
            self._search_payload(),
        )

    def _replace(self) -> None:
        query = self.find_edit.text()
        if not query:
            self._set_result(0)
            return

        self.replaceRequested.emit(
            query,
            self.replace_edit.text(),
            self._search_payload(),
        )
        self._update_count()

    def _replace_all(self) -> None:
        query = self.find_edit.text()
        if not query:
            self._set_result(0)
            return

        self.replaceAllRequested.emit(
            query,
            self.replace_edit.text(),
            self._search_payload(),
        )
        self._update_count()

    def _search_payload(self) -> dict[str, object]:
        options = self.options()

        return {
            "case_sensitive": options.case_sensitive,
            "whole_word": options.whole_word,
            "regex": options.regex,
            "scope": self.scope_value(),
        }

    # ------------------------------------------------------------------
    # Counting
    # ------------------------------------------------------------------

    def _update_count(self, *_args) -> None:
        query = self.find_edit.text()
        if not query:
            self._set_result(0)
            return

        total = 0

        for document in self._documents():
            text = self._document_text(document)
            total += self._count_matches(text, query)

        self._set_result(total)

    def _documents(self) -> list[object]:
        if self.scope_value() == "current":
            current = self._current_document_provider()
            if current is None:
                return []
            return [current]

        return list(self._document_provider())

    def _document_text(self, document: object) -> str:
        getter = getattr(document, "text", None)
        if callable(getter):
            try:
                return str(getter())
            except (RuntimeError, TypeError):
                return ""

        editor = getattr(document, "editor", None)
        if editor is not None:
            getter = getattr(editor, "text", None)
            if callable(getter):
                try:
                    return str(getter())
                except (RuntimeError, TypeError):
                    return ""

        return ""

    def _count_matches(self, text: str, query: str) -> int:
        pattern = self._build_pattern(query)

        if pattern is None:
            return 0

        try:
            return sum(1 for _match in pattern.finditer(text))
        except (re.error, TypeError):
            return 0

    def _build_pattern(self, query: str):
        if not self.regex_check.isChecked():
            query = re.escape(query)

        if self.whole_check.isChecked():
            query = rf"\b{query}\b"

        flags = 0

        if not self.case_check.isChecked():
            flags |= re.IGNORECASE

        try:
            return re.compile(query, flags)
        except re.error:
            return None

    def _set_result(self, count: int) -> None:
        if count <= 0:
            self.result_label.setText(
                self._tr("ui.no_results", "Nessun risultato")
            )
            return

        self.result_label.setText(
            self._tr("ui.results", "{count} risultati").format(
                count=count
            )
        )
