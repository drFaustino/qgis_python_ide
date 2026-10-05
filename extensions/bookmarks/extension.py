"""Bookmarks: segnalibri di riga nei file aperti dell'IDE.

Doppio clic su un segnalibro riapre il file e posiziona il cursore
sulla riga salvata. I segnalibri sono tenuti in memoria per la
sessione corrente dell'IDE.
"""

import os

from qgis.PyQt.QtGui import QAction
from qgis.PyQt.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QListWidget,
    QPushButton,
    QVBoxLayout,
)

from qgis_python_ide.core.ext_i18n import ExtensionBase


class BookmarksExtension(ExtensionBase):
    name = "Bookmarks"
    actions = []

    def __init__(self):
        super().__init__()
        self._marks = {}  # path -> [(line, note)]

    def _log(self, message, level="INFO"):
        if self._window is not None:
            try:
                self._window.log.append(
                    f"Bookmarks: {message}", level
                )
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Aggiungi
    # ------------------------------------------------------------------

    def _add(self):
        tab = self._window.current()

        if tab is None:
            return

        path = getattr(tab, "path", None)

        if not path:
            self._log(self.tr("no_path"), "WARNING")
            return

        editor = getattr(tab, "editor", None)
        line = 1

        if editor is not None and hasattr(
            editor, "getCursorPosition"
        ):
            try:
                line = editor.getCursorPosition()[0] + 1
            except Exception:
                line = 1

        note = f"{os.path.basename(path)}:{line}"
        self._marks.setdefault(path, []).append((line, note))
        self._log(f"{self.tr('added')}: {note}")

    # ------------------------------------------------------------------
    # Gestione
    # ------------------------------------------------------------------

    def _entries(self):
        """Elenco flat (path, line, note) per il dialog."""
        entries = []

        for path in sorted(self._marks):
            for line, note in self._marks[path]:
                entries.append((path, line, note))

        return entries

    def _show(self):
        dialog = QDialog(self._window)
        dialog.setWindowTitle(self.tr("title"))
        dialog.resize(480, 360)

        layout = QVBoxLayout(dialog)

        listing = QListWidget(dialog)
        entries = self._entries()

        for _path, _line, note in entries:
            listing.addItem(note)

        layout.addWidget(listing, 1)

        buttons_row = QHBoxLayout()
        go_button = QPushButton(self.tr("go"), dialog)
        clear_button = QPushButton(self.tr("clear"), dialog)
        buttons_row.addStretch(1)
        buttons_row.addWidget(go_button)
        buttons_row.addWidget(clear_button)
        layout.addLayout(buttons_row)

        def do_go():
            row = listing.currentRow()

            if row < 0 or row >= len(entries):
                return

            path, line, _note = entries[row]
            self._window._open_path(path)
            tab = self._window.current()

            if tab is not None and hasattr(tab, "goto_line"):
                try:
                    tab.goto_line(line)
                except Exception:
                    pass

            dialog.accept()

        def do_clear():
            self._marks.clear()
            listing.clear()
            self._log(self.tr("empty"))

        go_button.clicked.connect(do_go)
        clear_button.clicked.connect(do_clear)
        listing.itemDoubleClicked.connect(lambda _item: do_go())

        if not entries:
            listing.addItem(self.tr("empty"))

        dialog.exec()

    def register(self, window):
        self._window = window


# ------------------------------------------------------------------
# Contratto del modulo (usato da ExtensionManager)
# ------------------------------------------------------------------

_INSTANCE = BookmarksExtension()


def _do_add():
    _INSTANCE._add()


def _do_show():
    _INSTANCE._show()


_action_add = QAction("🔖 Aggiungi segnalibro", None)
_action_add.triggered.connect(_do_add)

_action_manage = QAction("📑 Gestisci segnalibri…", None)
_action_manage.triggered.connect(_do_show)

_INSTANCE.actions = [
    _action_add,
    _action_manage,
]



def _warn_missing_catalog(window):
    """Segnala nel log se manca il catalogo per la lingua corrente."""
    if not _INSTANCE.has_catalog():
        try:
            window.log.append(
                "Bookmarks: "
                "nessun catalogo translations/"
                + _INSTANCE._lang()
                + ".json — uso i messaggi inline.",
                "WARNING",
            )
        except Exception:
            pass

def register(window):
    _warn_missing_catalog(window)
    _action_add.setText(_INSTANCE.tr("add"))
    _action_manage.setText(_INSTANCE.tr("manage"))
    _action_add.setIcon(_INSTANCE.icon("bookmark"))
    _action_manage.setIcon(_INSTANCE.icon("bookmark"))
    _INSTANCE.register(window)



def retranslate():
    """Aggiorna testi e icone delle azioni nella lingua corrente."""
    _action_add.setText(_INSTANCE.tr("add"))
    _action_add.setIcon(_INSTANCE.icon("bookmark"))
    _action_manage.setText(_INSTANCE.tr("manage"))
    _action_manage.setIcon(_INSTANCE.icon("bookmark"))


def create_extension():
    return _INSTANCE
