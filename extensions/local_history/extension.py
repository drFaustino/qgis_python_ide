"""Local History: snapshot automatici dei file salvati.

Crea una copia di ogni file salvato in '<cartella>/.ide_history/' così
puoi ripristinare o aprire versioni precedenti senza Git.
"""

import os
import shutil
import time

from qgis.PyQt.QtCore import QFileSystemWatcher, QTimer
from qgis.PyQt.QtGui import QAction
from qgis.PyQt.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from qgis_python_ide.core.ext_i18n import ExtensionBase


class LocalHistoryExtension(ExtensionBase):
    name = "Local History"
    actions = []

    #: Rotazione: numero massimo di snapshot conservati per file.
    MAX_SNAPSHOTS = 50

    #: Cartelle escluse dallo snapshot automatico.
    EXCLUDED_DIRS = (
        ".git", "__pycache__", ".ide_history",
        "node_modules", ".idea",
    )

    def __init__(self):
        super().__init__()
        self._watcher = None
        self._pending = set()

    def _log(self, message):
        if self._window is not None:
            try:
                self._window.log.append(
                    f"Local History: {message}", "INFO"
                )
            except Exception:  # nosec B110 -- guardia difensiva UI
                pass

    def _current_path(self):
        tab = self._window.current()
        return getattr(tab, "path", None) if tab else None

    # ------------------------------------------------------------------
    # Snapshot
    # ------------------------------------------------------------------

    @staticmethod
    def _history_dir(path):
        return os.path.join(os.path.dirname(path), ".ide_history")

    @staticmethod
    def _snapshot_path(path):
        stamp = time.strftime("%Y-%m-%d_%H-%M-%S")
        name = os.path.basename(path)
        return os.path.join(
            LocalHistoryExtension._history_dir(path),
            f"{stamp}__{name}",
        )

    def _is_excluded(self, path):
        parts = set(path.split(os.sep))
        return bool(parts & set(self.EXCLUDED_DIRS))

    def _rotate_snapshots(self, path):
        history_dir = self._history_dir(path)
        name = os.path.basename(path)

        try:
            entries = sorted(
                (
                    item for item in os.listdir(history_dir)
                    if item.endswith("__" + name)
                ),
                reverse=True,
            )
        except OSError:
            return

        for old in entries[self.MAX_SNAPSHOTS:]:
            try:
                os.remove(os.path.join(history_dir, old))
            except OSError:
                pass

    def _snapshot_file(self, path, content=None):
        try:
            if content is None:
                with open(
                    path, "r", encoding="utf-8",
                    errors="replace",
                ) as handle:
                    content = handle.read()

            os.makedirs(self._history_dir(path), exist_ok=True)

            target = self._snapshot_path(path)

            with open(target, "w", encoding="utf-8") as handle:
                handle.write(content)

            self._rotate_snapshots(path)
            return target

        except OSError:
            return None

    def _manual_snapshot(self):
        path = self._current_path()

        if not path:
            self._log(self.tr("no_path"))
            return

        tab = self._window.current()
        content = tab.text() if hasattr(tab, "text") else None

        target = self._snapshot_file(path, content)

        if target:
            self._log(f"{self.tr('snap_done')}: {target}")

    def _on_file_changed(self, path):
        """Snapshot automatico: il file è cambiato su disco."""
        if path in self._pending or self._is_excluded(path):
            return

        self._pending.add(path)
        QTimer.singleShot(
            400,
            lambda p=path: self._do_snapshot(p),
        )

    def _do_snapshot(self, path):
        self._pending.discard(path)

        try:
            if os.path.exists(path) and not self._is_excluded(path):
                self._snapshot_file(path)
        finally:
            if self._watcher is not None and os.path.exists(path):
                if path not in self._watcher.files():
                    self._watcher.addPath(path)

    def _refresh_watched(self):
        if self._watcher is None:
            return

        paths = set()

        try:
            for index in range(self._window.tabs.count()):
                tab = self._window.tabs.widget(index)
                path = getattr(tab, "path", None)
                if path and os.path.exists(path) \
                        and not self._is_excluded(path):
                    paths.add(path)
        except Exception:  # nosec B110 -- guardia difensiva UI
            pass

        for path in self._watcher.files():
            if path not in paths:
                self._watcher.removePath(path)

        for path in paths:
            if path not in self._watcher.files():
                self._watcher.addPath(path)

    # ------------------------------------------------------------------
    # Finestra cronologia
    # ------------------------------------------------------------------

    def _show_history(self):
        path = self._current_path()

        if not path:
            self._log(self.tr("no_path"))
            return

        history_dir = self._history_dir(path)
        snapshots = []

        if os.path.isdir(history_dir):
            name = os.path.basename(path)
            snapshots = sorted(
                (
                    item for item in os.listdir(history_dir)
                    if item.endswith("__" + name)
                ),
                reverse=True,
            )

        dialog = QDialog(self._window)
        dialog.setWindowTitle(
            f"{self.tr('title')} — {os.path.basename(path)}"
        )
        dialog.resize(560, 420)

        layout = QVBoxLayout(dialog)

        if snapshots:
            listing = QListWidget(dialog)
            listing.addItems(snapshots)
            listing.setCurrentRow(0)
            layout.addWidget(listing, 1)

            buttons_row = QHBoxLayout()

            open_button = QPushButton(self.tr("open"), dialog)
            restore_button = QPushButton(self.tr("restore"), dialog)

            buttons_row.addWidget(open_button)
            buttons_row.addWidget(restore_button)
            buttons_row.addStretch(1)
            layout.addLayout(buttons_row)

            def selected_snapshot():
                item = listing.currentItem()
                if item is None:
                    return None
                return os.path.join(history_dir, item.text())

            def do_open():
                target = selected_snapshot()
                if target:
                    self._window._open_path(target)

            def do_restore():
                target = selected_snapshot()
                if not target:
                    return

                answer = QMessageBox.question(
                    dialog,
                    self.tr("restore"),
                    self.tr("confirm_restore"),
                    (
                        QMessageBox.StandardButton.Yes
                        | QMessageBox.StandardButton.No
                    ),
                    QMessageBox.StandardButton.No,
                )

                if answer != QMessageBox.StandardButton.Yes:
                    return

                shutil.copyfile(target, path)

                for index in range(self._window.tabs.count()):
                    tab = self._window.tabs.widget(index)
                    if getattr(tab, "path", None) == path:
                        try:
                            with open(
                                target, "r", encoding="utf-8",
                                errors="replace",
                            ) as handle:
                                tab.replace_document_text(
                                    handle.read()
                                )
                        except OSError:
                            pass

                self._log(f"{self.tr('restored')}: {target}")

            open_button.clicked.connect(do_open)
            restore_button.clicked.connect(do_restore)

        else:
            layout.addWidget(QLabel(self.tr("empty"), dialog))

        close_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Close,
            parent=dialog,
        )
        close_box.rejected.connect(dialog.reject)
        close_box.accepted.connect(dialog.accept)
        layout.addWidget(close_box)

        dialog.exec()

    def register(self, window):
        self._window = window

        try:
            self._watcher = QFileSystemWatcher(window)
            self._watcher.fileChanged.connect(
                self._on_file_changed
            )

            self._refresh_timer = QTimer(window)
            self._refresh_timer.setInterval(2000)
            self._refresh_timer.timeout.connect(
                self._refresh_watched
            )
            self._refresh_timer.start()
        except Exception:
            self._watcher = None


# ------------------------------------------------------------------
# Contratto del modulo (usato da ExtensionManager)
# ------------------------------------------------------------------

_INSTANCE = LocalHistoryExtension()


def _do_snapshot():
    _INSTANCE._manual_snapshot()


def _do_history():
    _INSTANCE._show_history()


_action_snapshot = QAction("💾 Snapshot", None)
_action_snapshot.triggered.connect(_do_snapshot)

_action_history = QAction("🕘 Cronologia…", None)
_action_history.triggered.connect(_do_history)

_INSTANCE.actions = [
    _action_snapshot,
    _action_history,
]



def _warn_missing_catalog(window):
    """Segnala nel log se manca il catalogo per la lingua corrente."""
    if not _INSTANCE.has_catalog():
        try:
            window.log.append(
                "Local History: "
                "nessun catalogo translations/"
                + _INSTANCE._lang()
                + ".json — uso i messaggi inline.",
                "WARNING",
            )
        except Exception:  # nosec B110 -- guardia difensiva UI
            pass

def register(window):
    _warn_missing_catalog(window)
    # Testi tradotti nella lingua corrente (le azioni vengono
    # aggiunte al menu DOPO register()).
    _action_snapshot.setText(_INSTANCE.tr("snapshot"))
    _action_history.setText(_INSTANCE.tr("history"))
    _action_snapshot.setIcon(_INSTANCE.icon("history"))
    _action_history.setIcon(_INSTANCE.icon("history"))
    _INSTANCE.register(window)



def retranslate():
    """Aggiorna testi e icone delle azioni nella lingua corrente."""
    _action_snapshot.setText(_INSTANCE.tr("snapshot"))
    _action_snapshot.setIcon(_INSTANCE.icon("history"))
    _action_history.setText(_INSTANCE.tr("history"))
    _action_history.setIcon(_INSTANCE.icon("history"))


def create_extension():
    return _INSTANCE
