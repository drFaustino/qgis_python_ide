from __future__ import annotations

import ast
import io
import traceback
from contextlib import redirect_stdout, redirect_stderr

from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtGui import QFont
from qgis.PyQt.QtWidgets import (
    QHBoxLayout,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class PythonConsole(QWidget):
    """Console Python persistente per QGIS, con namespace condiviso e storico."""

    commandExecuted = pyqtSignal(str, bool)

    def __init__(self, iface=None, parent=None, translator=None):
        super().__init__(parent)
        self.iface = iface
        self._translator = translator
        self.history: list[str] = []
        self._history_index = -1
        self.namespace: dict[str, object] = {}
        self._bootstrap_namespace()

        root = QVBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)

        top = QHBoxLayout()
        top.addStretch(1)
        self.clear_button = QPushButton(self._tr("console.clear_output", "Clear output"))
        self.clear_button.clicked.connect(self.clear_output)
        top.addWidget(self.clear_button)
        self.reset_button = QPushButton(self._tr("console.reset_namespace", "Reset namespace"))
        self.reset_button.clicked.connect(self.reset_namespace)
        top.addWidget(self.reset_button)
        root.addLayout(top)

        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        self.output.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.output.setFont(QFont("Monospace"))
        root.addWidget(self.output, 2)

        self.input = QPlainTextEdit()
        self.input.setPlaceholderText(
            self._tr(
                "console.input_placeholder",
                "Enter Python. Ctrl+Enter executes; variables remain available.",
            )
        )
        self.input.setMaximumBlockCount(1000)
        self.input.setFont(QFont("Monospace"))
        self.input.installEventFilter(self)
        root.addWidget(self.input, 1)

        self.run_button = QPushButton(self._tr("console.run", "Run"))
        self.run_button.clicked.connect(self.execute)
        root.addWidget(self.run_button)

        self._write(self._tr(
            "console.ready",
            "Console ready. Namespace: iface, qgis, QgsProject, project.",
        ))

    def _tr(self, key, default=""):
        if callable(self._translator):
            return self._translator(key, default)
        return default or key

    def retranslate(self, translator=None):
        if translator is not None:
            self._translator = translator
        self.clear_button.setText(self._tr("console.clear_output", "Clear output"))
        self.reset_button.setText(self._tr("console.reset_namespace", "Reset namespace"))
        self.run_button.setText(self._tr("console.run", "Run"))
        self.input.setPlaceholderText(self._tr(
            "console.input_placeholder",
            "Enter Python. Ctrl+Enter executes; variables remain available.",
        ))
        self._write(self._tr(
            "console.ready",
            "Console ready. Namespace: iface, qgis, QgsProject, project.",
        ))

    def _bootstrap_namespace(self):
        self.namespace = {"__name__": "__qgis_python_ide_console__"}
        try:
            from qgis.utils import iface as qgis_iface
            self.namespace["iface"] = self.iface or qgis_iface
        except Exception:
            self.namespace["iface"] = self.iface
        try:
            from qgis.core import QgsProject
            self.namespace["QgsProject"] = QgsProject
            self.namespace["project"] = QgsProject.instance()
        except Exception as exc:
            self._write(f"{self._tr("console.warning_project", "Warning: QgsProject unavailable")}: {exc}")
        try:
            import qgis
            self.namespace["qgis"] = qgis
        except Exception as exc:
            self._write(f"{self._tr("console.warning_qgis", "Warning: qgis module unavailable")}: {exc}")

    def eventFilter(self, obj, event):
        if obj is self.input and event.type() == event.Type.KeyPress:
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                    self.execute()
                    return True
            if event.key() == Qt.Key.Key_Up:
                if not self.input.toPlainText().strip():
                    self._history_move(-1)
                    return True
            if event.key() == Qt.Key.Key_Down:
                if not self.input.toPlainText().strip():
                    self._history_move(1)
                    return True
        return super().eventFilter(obj, event)

    def _history_move(self, delta):
        if not self.history:
            return
        self._history_index = max(
            -1, min(len(self.history) - 1, self._history_index + delta)
        )
        self.input.setPlainText(
            "" if self._history_index < 0 else self.history[self._history_index]
        )
        self.input.moveCursor(self.input.textCursor().MoveOperation.End)

    def execute(self):
        source = self.input.toPlainText()
        if not source.strip():
            return
        self.history.append(source)
        self._history_index = -1
        self.input.clear()

        stdout = io.StringIO()
        stderr = io.StringIO()
        ok = True
        try:
            tree = ast.parse(source, mode="exec")
            compiled = compile(tree, "<qgis-python-ide-console>", "exec")
            with redirect_stdout(stdout), redirect_stderr(stderr):
                # Console interattiva: l'utente esegue codice volontariamente.
                exec(  # nosec - console Python interattiva dell'IDE
                    compiled, self.namespace, self.namespace
                )
        except Exception:
            ok = False
            stderr.write(traceback.format_exc())

        out = stdout.getvalue()
        err = stderr.getvalue()
        if out:
            self._write(out.rstrip())
        if err:
            self._write(err.rstrip(), error=not ok)
        if ok and not out and not err:
            self._write(self._tr("console.command_executed", "Command executed."))
        self.commandExecuted.emit(source, ok)

    def _write(self, text: str, error=False):
        prefix = "[ERROR] " if error else ""
        self.output.appendPlainText(prefix + str(text))

    def clear_output(self):
        self.output.clear()

    def reset_namespace(self):
        self._bootstrap_namespace()
        self._write(self._tr("console.namespace_reset", "Namespace reset."))
