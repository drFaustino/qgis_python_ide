"""Pannello TODO/FIXME (Menu di controllo): raccoglie i segnaposto
del progetto in un dock. Doppio clic su una voce apre il file alla riga
indicata. Il pannello si svuota automaticamente alla chiusura del
progetto.
"""

import os
import re

from qgis.PyQt.QtCore import Qt, QTimer
from qgis.PyQt.QtGui import QAction
from qgis.PyQt.QtWidgets import (
    QDockWidget,
    QMessageBox,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

MESSAGES = {
    "it": {
        "menu": "📝 Pannello TODO/FIXME",
        "toggle": "📋 Mostra menu di controllo",
        "dock": "Menu di controllo",
        "refresh": "🔄 Aggiorna",
        "clear": "🗑 Cancella",
        "empty": "Nessun segnaposto trovato nel progetto.",
        "no_project": "Apri prima un progetto.",
        "confirm_clear": "Cancellare tutti i segnaposto elencati nel pannello?",
        "col_type": "Tipo",
        "col_pos": "Posizione",
        "col_note": "Nota",
        "goto_line": "➤ Vai alla riga",
    },
    "en": {
        "menu": "📝 TODO/FIXME panel",
        "toggle": "📋 Show control menu",
        "dock": "Control menu",
        "refresh": "🔄 Refresh",
        "clear": "🗑 Clear",
        "empty": "No placeholders found in the project.",
        "no_project": "Open a project first.",
        "confirm_clear": "Clear all placeholders listed in the panel?",
        "col_type": "Type",
        "col_pos": "Position",
        "col_note": "Note",
        "goto_line": "➤ Go to line",
    },
}

PATTERN = re.compile(
    r"#\s*(TODO|FIXME|XXX|HACK)\b[:\s]*(.*)",
    re.IGNORECASE,
)

EXTENSIONS = (
    ".py", ".js", ".ts", ".qss", ".css", ".json",
    ".xml", ".ui", ".md",
)


from qgis_python_ide.core.ext_i18n import ExtensionBase


class TodoPanelExtension(ExtensionBase):
    name = "TODO/FIXME Panel"
    actions = []

    def __init__(self):
        super().__init__()
        self._dock = None
        self._tree = None
        self._action_toggle = None
        self._refresh_button = None
        self._clear_button = None
        self._goto_button = None
        self._connected = False
        self._cleanup_timer = None

    def _project_root(self):
        try:
            root = getattr(
                self._window, "project_root", ""
            )
            if root and os.path.isdir(root):
                return root
            return self._window.settings.get(
                "project_dir", ""
            )
        except Exception:
            return ""

    def _parent(self):
        return (
            self._dock
            if self._dock is not None
            else self._window
        )

    # ------------------------------------------------------------------
    # Pulsanti
    # ------------------------------------------------------------------

    def _clear(self):
        """Svuota il pannello dopo conferma dell'utente."""
        answer = QMessageBox.question(
            self._parent(),
            self.tr("clear"),
            self.tr("confirm_clear"),
            (
                QMessageBox.StandardButton.Yes
                | QMessageBox.StandardButton.No
            ),
            QMessageBox.StandardButton.No,
        )

        if answer != QMessageBox.StandardButton.Yes:
            return

        self._tree.clear()

    def _scan(self):
        """Aggiorna l'elenco dei segnaposto del progetto."""
        if self._tree is None:
            return

        self._tree.clear()

        root = self._project_root()

        if not root or not os.path.isdir(root):
            QMessageBox.warning(
                self._parent(),
                self.tr("dock"),
                self.tr("no_project"),
            )
            return

        found = 0

        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [
                d
                for d in dirnames
                if d not in ("__pycache__", ".git", ".idea")
            ]

            for filename in sorted(filenames):
                if not filename.endswith(EXTENSIONS):
                    continue

                path = os.path.join(dirpath, filename)

                try:
                    with open(
                        path, "r", encoding="utf-8",
                        errors="replace",
                    ) as handle:
                        for number, line in enumerate(
                            handle, start=1
                        ):
                            match = PATTERN.search(line)

                            if match:
                                kind = match.group(
                                    1
                                ).upper()
                                note = match.group(
                                    2
                                ).strip()[:120]

                                rel = os.path.relpath(
                                    path, root
                                )

                                item = QTreeWidgetItem(
                                    [
                                        kind,
                                        f"{rel}:{number}",
                                        note,
                                    ]
                                )
                                item.setData(
                                    0,
                                    Qt.ItemDataRole.UserRole,
                                    (path, number),
                                )
                                self._tree.addTopLevelItem(
                                    item
                                )
                                found += 1

                except OSError:
                    continue

        if not found:
            item = QTreeWidgetItem([self.tr("empty")])
            self._tree.addTopLevelItem(item)

    # ------------------------------------------------------------------
    # Pulizia automatica alla chiusura del progetto
    # ------------------------------------------------------------------

    def _cleanup_if_project_closed(self):
        """Svuota l'albero quando il progetto viene chiuso."""
        if self._tree is None:
            return

        if self._project_root():
            return

        if self._tree.topLevelItemCount() > 0:
            self._tree.clear()

    def _start_cleanup_timer(self):
        if self._cleanup_timer is not None:
            try:
                self._cleanup_timer.stop()
            except Exception:
                pass

        self._cleanup_timer = QTimer(self._window)
        self._cleanup_timer.setInterval(1500)
        self._cleanup_timer.timeout.connect(
            self._cleanup_if_project_closed
        )
        self._cleanup_timer.start()

    # ------------------------------------------------------------------
    # Navigazione
    # ------------------------------------------------------------------

    def _find_tab(self, path):
        """Restituisce la scheda già aperta per 'path' (selezionandola)."""
        try:
            for index in range(self._window.tabs.count()):
                tab = self._window.tabs.widget(index)

                if getattr(tab, "path", None) == path:
                    self._window.tabs.setCurrentIndex(index)
                    return tab
        except Exception:
            pass

        return None

    def _goto(self, item, _column=None):
        """Apre (o riusa) la scheda del file e posiziona il cursore."""
        if item is None:
            return

        data = item.data(0, Qt.ItemDataRole.UserRole)

        if not data:
            return

        path, line = data

        # Se la scheda è già aperta la riusa: niente duplicati.
        tab = self._find_tab(path)

        if tab is None:
            self._window._open_path(path)
            tab = self._window.current()

        if tab is not None and hasattr(tab, "editor"):
            try:
                tab.editor.setCursorPosition(line - 1, 0)
                tab.editor.ensureLineVisible(line - 1)
            except Exception:
                pass

    def _goto_selected(self):
        """Vai alla riga della voce attualmente selezionata nel pannello."""
        if self._tree is None:
            return

        item = self._tree.currentItem()

        if item is None:
            return

        self._goto(item)

    def _on_toggled(self, checked):
        if self._dock is None:
            return

        self._dock.setVisible(checked)

        if checked:
            self._scan()

    def register(self, window):
        self._window = window

        try:
            # A ogni ricarica il modulo viene rieseguito: rimuovi il
            # dock della registrazione precedente prima di ricrearlo.
            old_dock = getattr(
                window, "_todo_panel_dock", None
            )
            if old_dock is not None:
                try:
                    window.removeDockWidget(old_dock)
                except Exception:
                    pass

            self._dock = QDockWidget(
                self.tr("dock"), window
            )
            window._todo_panel_dock = self._dock
            self._dock.setObjectName("todoPanelDock")

            container = QWidget(self._dock)
            layout = QVBoxLayout(container)
            layout.setContentsMargins(4, 4, 4, 4)

            refresh_button = QPushButton(
                self.tr("refresh"), container
            )
            refresh_button.clicked.connect(self._scan)
            layout.addWidget(refresh_button)

            clear_button = QPushButton(
                self.tr("clear"), container
            )
            clear_button.clicked.connect(self._clear)
            layout.addWidget(clear_button)

            goto_button = QPushButton(
                self.tr("goto_line"), container
            )
            goto_button.clicked.connect(self._goto_selected)
            layout.addWidget(goto_button)

            self._refresh_button = refresh_button
            self._clear_button = clear_button
            self._goto_button = goto_button

            self._tree = QTreeWidget(container)
            self._tree.setHeaderLabels(
                [
                    self.tr("col_type"),
                    self.tr("col_pos"),
                    self.tr("col_note"),
                ]
            )
            self._tree.setColumnWidth(0, 70)
            self._tree.setColumnWidth(1, 220)
            self._tree.itemDoubleClicked.connect(
                self._goto
            )
            layout.addWidget(self._tree, 1)

            self._dock.setWidget(container)

            window.addDockWidget(
                Qt.DockWidgetArea.RightDockWidgetArea,
                self._dock,
            )

            self._dock.setVisible(False)

            self._start_cleanup_timer()

            if self._action_toggle is not None:
                self._action_toggle.setText(
                    self.tr("toggle")
                )
                self._action_toggle.setIcon(
                    self.icon("todo")
                )
                self._action_toggle.setCheckable(True)

                if not self._connected:
                    self._connected = True
                    self._action_toggle.toggled.connect(
                        self._on_toggled
                    )
                    self._dock.visibilityChanged.connect(
                        self._action_toggle.setChecked
                    )

        except Exception:
            pass


# ------------------------------------------------------------------
# Contratto del modulo (usato da ExtensionManager)
# ------------------------------------------------------------------

_INSTANCE = TodoPanelExtension()


# NOTA: l'azione e' checkable -> il clic scatta 'toggled', non serve
# 'triggered': collegarli entrambi causerebbe un doppio toggle che
# lascerebbe il pannello sempre chiuso.
_action_toggle = QAction("📋 Mostra menu di controllo", None)
_action_toggle.setCheckable(True)

_INSTANCE.actions = [_action_toggle]
_INSTANCE._action_toggle = _action_toggle


def register(window):
    _action_toggle.setText(
        _INSTANCE.tr("toggle")
    )
    _action_toggle.setIcon(_INSTANCE.icon("todo"))
    _INSTANCE.register(window)

    if not _INSTANCE.has_catalog():
        try:
            window.log.append(
                "TODO Panel: "
                f"nessun catalogo translations/"
                f"{_INSTANCE._lang()}.json — "
                "uso i messaggi inline.",
                "WARNING",
            )
        except Exception:
            pass


def retranslate():
    """Aggiorna testi e icone nella lingua corrente dell'IDE."""
    if _INSTANCE._action_toggle is not None:
        _action_toggle.setText(_INSTANCE.tr("toggle"))
        _action_toggle.setIcon(_INSTANCE.icon("todo"))

    if _INSTANCE._dock is not None:
        _INSTANCE._dock.setWindowTitle(_INSTANCE.tr("dock"))

    if _INSTANCE._tree is not None:
        _INSTANCE._tree.setHeaderLabels(
            [
                _INSTANCE.tr("col_type"),
                _INSTANCE.tr("col_pos"),
                _INSTANCE.tr("col_note"),
            ]
        )

    if _INSTANCE._refresh_button is not None:
        _INSTANCE._refresh_button.setText(
            _INSTANCE.tr("refresh")
        )

    if _INSTANCE._clear_button is not None:
        _INSTANCE._clear_button.setText(
            _INSTANCE.tr("clear")
        )

    if _INSTANCE._goto_button is not None:
        _INSTANCE._goto_button.setText(
            _INSTANCE.tr("goto_line")
        )


def create_extension():
    return _INSTANCE
