from __future__ import annotations

import ast
import json
import os
import py_compile
from dataclasses import dataclass


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str = ""


class PluginSelfChecker:
    """Controlli non distruttivi del pacchetto IDE e delle sue traduzioni."""

    def __init__(self, root: str):
        self.root = os.path.abspath(root)

    def run(self) -> list[CheckResult]:
        results = []
        results.extend(self._python_files())
        results.extend(self._translations())
        results.extend(self._required_files())
        results.extend(self._module_imports())
        results.extend(self._qt_symbols())
        results.extend(self._qgis_runtime())
        return results

    def _python_files(self):
        out = []
        for directory, _, files in os.walk(self.root):
            for filename in files:
                if not filename.endswith(".py"):
                    continue
                path = os.path.join(directory, filename)
                try:
                    source = open(path, "r", encoding="utf-8").read()
                    ast.parse(source, filename=path)
                    compile(source, path, "exec")
                    out.append(CheckResult(
                        f"Python: {os.path.relpath(path, self.root)}", True
                    ))
                except Exception as exc:
                    out.append(CheckResult(
                        f"Python: {os.path.relpath(path, self.root)}", False, str(exc)
                    ))
        return out

    def _translations(self):
        folder = os.path.join(self.root, "translations")
        files = sorted(f for f in os.listdir(folder) if f.endswith(".json"))
        catalogs = {}
        out = []
        for filename in files:
            path = os.path.join(folder, filename)
            try:
                data = json.load(open(path, encoding="utf-8"))
                if not isinstance(data, dict):
                    raise ValueError("catalogo non valido")
                catalogs[filename] = data
                out.append(CheckResult(f"Traduzione: {filename}", True))
            except Exception as exc:
                out.append(CheckResult(f"Traduzione: {filename}", False, str(exc)))
        if catalogs:
            reference = set(catalogs.get("en.json", next(iter(catalogs.values()))))
            for filename, data in catalogs.items():
                missing = sorted(reference - set(data))
                if missing:
                    out.append(CheckResult(
                        f"Chiavi traduzione: {filename}", False,
                        f"{len(missing)} chiavi mancanti: {', '.join(missing[:8])}"
                    ))
                else:
                    out.append(CheckResult(f"Chiavi traduzione: {filename}", True))
        return out

    def _module_imports(self):
        """Importa tutti i moduli runtime del plugin, non solo quelli core.

        Questo controllo deve intercettare anche errori di importazione nelle
        parti UI prima che l'utente apra l'IDE (ad esempio un QActionGroup
        importato dal modulo Qt sbagliato).
        """
        package = os.path.basename(self.root.rstrip(os.sep))
        modules = (
            f"{package}.core.i18n",
            f"{package}.core.settings",
            f"{package}.core.analyzer",
            f"{package}.core.language_service",
            f"{package}.core.runner",
            f"{package}.core.commands",
            f"{package}.core.api_indexer",
            f"{package}.core.self_check",
            f"{package}.core.extensions",
            f"{package}.core.formatters",
            f"{package}.widgets.log_panel",
            f"{package}.widgets.python_console",
            f"{package}.widgets.editor_tab",
            f"{package}.widgets.markdown_toolbar",
            f"{package}.widgets.completion_popup",
            f"{package}.widgets.find_replace_panel",
            f"{package}.ui.main_window",
            f"{package}.python_ide",
        )
        out = []
        import importlib
        import sys

        parent = os.path.dirname(self.root)
        if parent not in sys.path:
            sys.path.insert(0, parent)

        for name in modules:
            try:
                importlib.import_module(name)
                out.append(CheckResult(f"Import: {name}", True))
            except Exception as exc:
                out.append(CheckResult(f"Import: {name}", False, str(exc)))
        return out

    def _qt_symbols(self):
        """Verifica gli import Qt6 fondamentali usati dall'interfaccia."""
        try:
            from qgis.PyQt.QtGui import QAction, QActionGroup
            from qgis.PyQt.QtWidgets import QMainWindow, QMenu
            from qgis.gui import QgsCodeEditorPython
            ok = all((QAction, QActionGroup, QMainWindow, QMenu, QgsCodeEditorPython))
            return [CheckResult("Qt/QGIS UI symbols", bool(ok))]
        except Exception as exc:
            return [CheckResult("Qt/QGIS UI symbols", False, str(exc))]

    def _required_files(self):
        required = ("metadata.txt", "icon.svg", "core/i18n.py", "ui/main_window.py")
        return [
            CheckResult(f"File richiesto: {path}", os.path.isfile(os.path.join(self.root, path)))
            for path in required
        ]

    def _qgis_runtime(self):
        try:
            import qgis
            from qgis.core import QgsProject
            return [
                CheckResult("Runtime QGIS", True, getattr(qgis, "__version__", "disponibile")),
                CheckResult("QgsProject", QgsProject is not None),
            ]
        except Exception as exc:
            return [CheckResult("Runtime QGIS", False, str(exc))]
