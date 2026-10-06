from pathlib import Path

p = Path(__file__).parents[1] / "ui" / "main_window.py"
s = p.read_text(encoding="utf-8")

assert "QMenu(title, menubar)" in s  # nosec B101 -- test
assert "project_menu = create_menu(" in s  # nosec B101 -- test
assert "button.setIcon(" in s  # nosec B101 -- test
assert "self.act_console" in s  # nosec B101 -- test
assert "status.language" in s  # nosec B101 -- test
assert "self._reload_qgis_runtime" in s  # nosec B101 -- test
assert "ApiIndexer" in s  # nosec B101 -- test
assert "PythonConsole(" in s  # nosec B101 -- test
assert "self._save_dock_layout" in s  # nosec B101 -- test
assert "self._reset_dock_layout" in s  # nosec B101 -- test
assert 'view_menu.addAction(self.act_save_dock_layout)' in s  # nosec B101 -- test
assert 'view_menu.addAction(self.act_reset_dock_layout)' in s  # nosec B101 -- test
assert 'self.addToolBar' not in s[s.find('self.act_save_dock_layout'):s.find('self.act_reset_dock_layout')+100]  # nosec B101 -- test
assert 'restoreState(saved_docks, 220)' in s  # nosec B101 -- test


# Regression: QActionGroup is provided by QtGui in Qt6/QGIS 4.
assert "QActionGroup" in s  # nosec B101 -- test
assert "from qgis.PyQt.QtGui import (" in s  # nosec B101 -- test
assert "    QActionGroup," in s  # nosec B101 -- test


# QAction/QActionGroup live in QtGui with Qt6/QGIS 4, not QtWidgets.
python_ide = (Path(__file__).parents[1] / "python_ide.py").read_text(encoding="utf-8")
assert "from qgis.PyQt.QtGui import QAction, QIcon" in python_ide  # nosec B101 -- test
assert "from qgis.PyQt.QtWidgets import QAction" not in python_ide  # nosec B101 -- test


# Markdown/new-file regressions.
editor_tab = (Path(__file__).parents[1] / "widgets" / "editor_tab.py").read_text(encoding="utf-8")
main_window = (Path(__file__).parents[1] / "ui" / "main_window.py").read_text(encoding="utf-8")
assert "def _markdown_preview_context_menu" in editor_tab  # nosec B101 -- test
assert "apply_theme" not in editor_tab  # nosec B101 -- test
assert "initial_suffix=extension" in main_window  # nosec B101 -- test
assert "tab.suggested_name = filename" in main_window  # nosec B101 -- test
assert "else self._tab_suffix(tab)" in main_window  # nosec B101 -- test
assert "context.refresh_markdown_preview" in (Path(__file__).parents[1] / "translations" / "it.json").read_text(encoding="utf-8")  # nosec B101 -- test
