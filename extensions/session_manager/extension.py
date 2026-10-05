"""Session Manager: salva e ripristina insiemi di schede aperte.

Le sessioni sono salvate in ~/.qgis_ide_sessions.json con nome, data
e elenco dei percorsi dei file aperti nell'IDE.
"""

import json
import os
import time

from qgis.PyQt.QtGui import QAction
from qgis.PyQt.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QInputDialog,
    QListWidget,
    QPushButton,
    QVBoxLayout,
)

from qgis_python_ide.core.ext_i18n import ExtensionBase

STORE = os.path.expanduser("~/.qgis_ide_sessions.json")


class SessionManagerExtension(ExtensionBase):
    name = "Session Manager"
    actions = []

    def __init__(self):
        super().__init__()

    def _log(self, message, level="INFO"):
        if self._window is not None:
            try:
                self._window.log.append(
                    f"Session Manager: {message}", level
                )
            except Exception:
                pass

    @staticmethod
    def _read():
        try:
            with open(STORE, "r", encoding="utf-8") as handle:
                data = json.load(handle)

            if isinstance(data, dict):
                return data
        except (OSError, ValueError):
            pass

        return {}

    @staticmethod
    def _write(data):
        with open(STORE, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, ensure_ascii=False)

    # ------------------------------------------------------------------
    # Salva
    # ------------------------------------------------------------------

    def _save(self):
        name, ok = QInputDialog.getText(
            self._window,
            self.tr("save"),
            self.tr("name_prompt"),
        )

        if not ok or not name.strip():
            return

        files = []

        for index in range(self._window.tabs.count()):
            tab = self._window.tabs.widget(index)
            path = getattr(tab, "path", None)

            if path:
                files.append(path)

        data = self._read()
        data[name.strip()] = {
            "when": time.strftime("%Y-%m-%d %H:%M"),
            "files": files,
        }
        self._write(data)
        self._log(self.tr("saved"))

    # ------------------------------------------------------------------
    # Carica
    # ------------------------------------------------------------------

    def _load(self):
        data = self._read()

        if not data:
            self._log(self.tr("empty"), "WARNING")
            return

        dialog = QDialog(self._window)
        dialog.setWindowTitle(self.tr("title"))
        dialog.resize(460, 340)

        layout = QVBoxLayout(dialog)

        listing = QListWidget(dialog)

        for name, payload in sorted(
            data.items(),
            key=lambda item: item[1].get("when", ""),
            reverse=True,
        ):
            when = payload.get("when", "")
            count = len(payload.get("files", []))
            listing.addItem(
                f"{name}  ({when} — {count})"
            )

        listing.setCurrentRow(0)
        layout.addWidget(listing, 1)

        buttons_row = QHBoxLayout()
        open_button = QPushButton(self.tr("open"), dialog)
        delete_button = QPushButton(self.tr("delete"), dialog)
        buttons_row.addStretch(1)
        buttons_row.addWidget(open_button)
        buttons_row.addWidget(delete_button)
        layout.addLayout(buttons_row)

        def selected_name():
            item = listing.currentItem()

            if item is None:
                return None

            return item.text().split("  (")[0]

        def do_open():
            name = selected_name()

            if not name or name not in data:
                return

            for path in data[name].get("files", []):
                if os.path.exists(path):
                    self._window._open_path(path)

            dialog.accept()

        def do_delete():
            name = selected_name()

            if not name or name not in data:
                return

            del data[name]
            self._write(data)
            row = listing.currentRow()
            listing.takeItem(row)
            self._log(f"{self.tr('deleted')}: {name}")

        open_button.clicked.connect(do_open)
        delete_button.clicked.connect(do_delete)
        listing.itemDoubleClicked.connect(lambda _item: do_open())

        dialog.exec()

    def register(self, window):
        self._window = window


# ------------------------------------------------------------------
# Contratto del modulo (usato da ExtensionManager)
# ------------------------------------------------------------------

_INSTANCE = SessionManagerExtension()


def _do_save():
    _INSTANCE._save()


def _do_load():
    _INSTANCE._load()


_action_save = QAction("💾 Salva sessione…", None)
_action_save.triggered.connect(_do_save)

_action_load = QAction("📂 Carica sessione…", None)
_action_load.triggered.connect(_do_load)

_INSTANCE.actions = [
    _action_save,
    _action_load,
]



def _warn_missing_catalog(window):
    """Segnala nel log se manca il catalogo per la lingua corrente."""
    if not _INSTANCE.has_catalog():
        try:
            window.log.append(
                "Session Manager: "
                "nessun catalogo translations/"
                + _INSTANCE._lang()
                + ".json — uso i messaggi inline.",
                "WARNING",
            )
        except Exception:
            pass

def register(window):
    _warn_missing_catalog(window)
    _action_save.setText(_INSTANCE.tr("save"))
    _action_load.setText(_INSTANCE.tr("load"))
    _action_save.setIcon(_INSTANCE.icon("session"))
    _action_load.setIcon(_INSTANCE.icon("session"))
    _INSTANCE.register(window)



def retranslate():
    """Aggiorna testi e icone delle azioni nella lingua corrente."""
    _action_save.setText(_INSTANCE.tr("save"))
    _action_save.setIcon(_INSTANCE.icon("session"))
    _action_load.setText(_INSTANCE.tr("load"))
    _action_load.setIcon(_INSTANCE.icon("session"))


def create_extension():
    return _INSTANCE
