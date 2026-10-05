from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys

from pathlib import Path
from datetime import datetime

from qgis.PyQt.QtCore import Qt, QSettings, QUrl, QSize, QTimer
from qgis.PyQt.QtGui import (
    QAction,
    QActionGroup,
    QKeySequence,
    QDesktopServices,
    QIcon,
    QColor,
)
from qgis.core import QgsProject

from qgis.PyQt.QtWidgets import (
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QSplitter,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QDockWidget,
    QFileDialog,
    QMessageBox,
    QToolBar,
    QLabel,
    QPushButton,
    QInputDialog,
    QMenu,
    QLineEdit,
    QStatusBar,
    QProgressBar,
    QTextBrowser,
    QListWidget,
    QListWidgetItem,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QCheckBox,
    QSizePolicy,
    QStyle,
    QApplication,
    QToolButton,
)

from ..core.analyzer import QGISPythonAnalyzer, normalize_whitespace
from ..core.designer import open_designer, compile_ui
from ..core.runner import ScriptRunner
from ..core.snippets import SnippetStore
from ..core.settings import IDESettings
from ..core.language_service import PyQGISLanguageService
from ..core.completion_service import complete_editor
from ..core.formatters import format_document, trim_trailing
from ..core.i18n import I18n
from ..core.extensions import ExtensionManager
from ..core.commands import CommandRegistry
from ..core.api_indexer import ApiIndexer
from ..core.self_check import PluginSelfChecker

from ..widgets.editor_tab import EditorTab
from ..widgets.log_panel import LogPanel
from ..widgets.completion_popup import CompletionPopup
from ..widgets.python_console import PythonConsole

from qgis_python_ide.widgets.find_replace_panel import FindReplacePanel


class IDEMainWindow(QMainWindow):

    def __init__(self, iface, language_service=None):
        super().__init__(None)

        self.iface = iface

        self.setWindowFlags(
            Qt.WindowType.Window
            | Qt.WindowType.WindowMinMaxButtonsHint
            | Qt.WindowType.WindowCloseButtonHint
        )

        self.setWindowModality(Qt.WindowModality.NonModal)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)

        self.settings = IDESettings()
        self.project_root = ""

        # Il percorso del progetto non viene mai ereditato dalla
        # sessione precedente: al primo avvio l'IDE non deve sapere
        # quale progetto era aperto. Il valore persistito viene
        # azzerato; viene riscritto solo aprendo un progetto.
        self.settings.set(
            "project_dir",
            "",
        )

        self.i18n = I18n(self.settings)
        self.analyzer = QGISPythonAnalyzer()
        self.language = language_service or PyQGISLanguageService()
        self.snippets = SnippetStore()
        self.commands = CommandRegistry()
        self.api_indexer = ApiIndexer(self.language)

        self.extensions = ExtensionManager(
            os.path.dirname(os.path.dirname(__file__))
        )

        self.runner = ScriptRunner(iface, self)
        self.runner.output.connect(self._runner_output)
        self.runner.finished.connect(self._runner_finished)

        self.setWindowTitle("QGIS Python IDE Pro 1.0.0")
        self.setWindowIcon(self.icon("ide"))

        self.resize(1720, 1050)
        self.setMinimumSize(1050, 680)
        self.setDockNestingEnabled(True)

        self._ui_previews = []

        self._build_ui()
        self._build_actions()
        self._default_dock_state = self.saveState()
        self._restore()

        self.extensions.discover()
        self._load_extensions_ui()
        self._new_python()
        QTimer.singleShot(0, self._start_initial_api_index)

    def _t(self, key: str, default: str = "") -> str:
        return self.i18n.tr(key, default or key)

    def _finish_progress(self, format_text: str) -> None:
        """Mostra il completamento al 100%, poi riporta la barra a 0%."""
        self.progress.setRange(0, 100)
        self.progress.setValue(100)
        self.progress.setFormat(format_text)
        QTimer.singleShot(650, self._reset_progress)

    def _reset_progress(self) -> None:
        self.progress.setValue(0)
        self.progress.hide()

    def _start_initial_api_index(self):
        started, signals = self.api_indexer.start(False)
        if not started:
            return
        self.progress.show()
        self.progress.setRange(0, 0)
        self.status_msg.setText(self._t("status.indexing_api", "Indicizzazione API QGIS…"))
        signals.finished.connect(self._api_index_finished)
        signals.failed.connect(self._api_index_failed)

    def _api_index_finished(self, ok, message, count):
        self._finish_progress(self._t("status.ready", "Pronto"))
        self.status_msg.setText(
            self._t("status.api_indexed", "API indicizzate: {count} simboli").format(count=count)
        )
        self._populate_api()

    def _api_index_failed(self, message):
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.hide()
        self.status_msg.setText(self._t("status.api_index_failed", "Indicizzazione API non riuscita"))
        self._runner_output(message, "ERROR")

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    def icon(self, name):
        path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "icons",
            f"{name}.svg",
        )

        if os.path.exists(path):
            return QIcon(path)

        return QIcon()

    def _dock(self, title, widget, area, obj, icon=None):
        dock = QDockWidget(title, self)

        dock.setObjectName(obj)
        dock.setWidget(widget)
        dock.setMinimumWidth(260)

        dock.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetMovable
            | QDockWidget.DockWidgetFeature.DockWidgetFloatable
            | QDockWidget.DockWidgetFeature.DockWidgetClosable
        )

        if icon:
            dock.setWindowIcon(self.icon(icon))

        self.addDockWidget(area, dock)

        return dock

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self):
        central = QWidget()
        root = QVBoxLayout(central)

        root.setContentsMargins(2, 2, 2, 2)
        root.setSpacing(3)

        # --------------------------------------------------------------
        # Tabs / Editor
        # --------------------------------------------------------------

        self.tabs = QTabWidget()
        self.tabs.setTabsClosable(True)
        self.tabs.setMovable(True)
        self.tabs.setDocumentMode(True)
        self.tabs.setElideMode(
            Qt.TextElideMode.ElideNone
        )

        self.tabs.tabCloseRequested.connect(
            self._close_tab
        )

        # Menu contestuale delle schede.
        self.tabs.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu
        )
        self.tabs.customContextMenuRequested.connect(
            self._tabs_context_menu
        )

        self.tabs.currentChanged.connect(
            lambda _: self._on_current_tab_changed()
        )

        root.addWidget(self.tabs, 1)

        self.setCentralWidget(central)

        # --------------------------------------------------------------
        # Find / Replace
        # --------------------------------------------------------------

        self.find_replace = FindReplacePanel(
            self._open_documents,
            self._current_document,
            self,
        )

        self.find_replace.retranslate(
            self._t
        )

        self.find_replace.navigateRequested.connect(
            self._find_replace_navigate
        )

        self.find_replace.replaceRequested.connect(
            self._find_replace_replace
        )

        self.find_replace.replaceAllRequested.connect(
            self._find_replace_replace_all
        )

        self.find_replace_dock = self._dock(
            self._t(
                "dock.find_replace",
                "Trova e sostituisci",
            ),
            self.find_replace,
            Qt.DockWidgetArea.BottomDockWidgetArea,
            "FindReplaceDock",
            "search",
        )

        self.find_replace_dock.hide()

        self.tabs.currentChanged.connect(
            self._find_replace_document_changed
        )

        # --------------------------------------------------------------
        # Project explorer
        # --------------------------------------------------------------

        self.project = QTreeWidget()

        self.project.setObjectName(
            "projectTree"
        )

        self.project.setHeaderLabels(
            [
                self._t(
                    "ui.project_files",
                    "Progetto / File",
                )
            ]
        )

        self.project.setAlternatingRowColors(
            True
        )

        self.project.setRootIsDecorated(
            True
        )

        self.project.setUniformRowHeights(
            False
        )

        self.project.itemDoubleClicked.connect(
            self._project_open
        )

        # Contenitore con barra superiore: include il pulsante visibile
        # "Ricarica file del progetto" per aggiornare l'elenco dei file.
        project_box = QWidget()
        project_layout = QVBoxLayout(project_box)
        project_layout.setContentsMargins(0, 0, 0, 0)
        project_layout.setSpacing(2)

        project_bar = QHBoxLayout()
        project_bar.setContentsMargins(4, 2, 4, 0)

        self.project_reload_button = QToolButton()
        self.project_reload_button.setText(
            self._t(
                "ui.reload_project",
                "Ricarica file del progetto",
            )
        )
        self.project_reload_button.setToolTip(
            self._t(
                "ui.reload_project",
                "Ricarica file del progetto",
            )
        )
        self.project_reload_button.setIcon(
            self.icon("refresh")
        )
        self.project_reload_button.setAutoRaise(True)
        self.project_reload_button.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonTextBesideIcon
        )
        self.project_reload_button.clicked.connect(
            self._reload_project_files
        )

        project_bar.addWidget(
            self.project_reload_button
        )
        project_bar.addStretch(1)

        project_layout.addLayout(project_bar)
        project_layout.addWidget(self.project)

        self.project_dock = self._dock(
            self._t(
                "dock.project",
                "Esplora progetto",
            ),
            project_box,
            Qt.DockWidgetArea.LeftDockWidgetArea,
            "ProjectDock",
            "project",
        )

        # --------------------------------------------------------------
        # Diagnostics
        # --------------------------------------------------------------

        self.diag = QTreeWidget()

        self.diag.setObjectName(
            "diagnosticsTree"
        )

        self.diag.setHeaderLabels(
            [
                self._t("ui.line", "Riga"),
                self._t("ui.column", "Col."),
                self._t("ui.level", "Livello"),
                self._t(
                    "ui.diagnostic",
                    "Diagnostica",
                ),
                self._t("ui.code", "Codice"),
            ]
        )

        self.diag.setAlternatingRowColors(
            True
        )

        self.diag.setRootIsDecorated(
            True
        )

        self.diag.setUniformRowHeights(
            False
        )

        self.diag.itemDoubleClicked.connect(
            self._goto_diag
        )

        # Menu contestuale della scheda Diagnostica.
        self.diag.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu
        )
        self.diag.customContextMenuRequested.connect(
            self._diag_context_menu
        )

        self.diag_dock = self._dock(
            self._t(
                "dock.diagnostics",
                "Diagnostica / Quick Fix",
            ),
            self.diag,
            Qt.DockWidgetArea.RightDockWidgetArea,
            "DiagnosticsDock",
            "check",
        )

        # --------------------------------------------------------------
        # API
        # --------------------------------------------------------------

        api = QWidget()

        al = QVBoxLayout(api)
        al.setContentsMargins(
            6,
            6,
            6,
            6,
        )

        self.api_search = QLineEdit()

        self.api_search.setPlaceholderText(
            self._t(
                "ui.api_search",
                "Cerca nelle API QGIS…",
            )
        )

        al.addWidget(
            self.api_search
        )

        self.api_list = QListWidget()

        al.addWidget(
            self.api_list,
            2,
        )

        self.api_doc = QTextBrowser()

        al.addWidget(
            self.api_doc,
            1,
        )

        self.api_list.itemClicked.connect(
            self._show_api_item
        )

        self.api_search.textChanged.connect(
            self._filter_api
        )

        self.api_dock = self._dock(
            self._t(
                "dock.api",
                "Documentazione API / PyQGIS",
            ),
            api,
            Qt.DockWidgetArea.RightDockWidgetArea,
            "ApiDock",
            "docs",
        )

        # --------------------------------------------------------------
        # Log
        # --------------------------------------------------------------

        self.log = LogPanel()

        self.log.retranslate(
            self._t
        )

        self.log_dock = self._dock(
            self._t(
                "log.title",
                "Log / Processi",
            ),
            self.log,
            Qt.DockWidgetArea.BottomDockWidgetArea,
            "LogDock",
            "terminal",
        )

        # --------------------------------------------------------------
        # Python console
        # --------------------------------------------------------------

        self.console = PythonConsole(
            self.iface,
            self,
            self._t,
        )

        self.console.commandExecuted.connect(
            lambda source, ok: self.log.append(
                self._t(
                    "log.console_ok",
                    "Console: comando eseguito",
                )
                if ok
                else self._t(
                    "log.console_error",
                    "Console: comando terminato con errore",
                ),
                "INFO" if ok else "ERROR",
            )
        )

        self.console_dock = self._dock(
            self._t(
                "dock.console",
                "Console Python",
            ),
            self.console,
            Qt.DockWidgetArea.BottomDockWidgetArea,
            "PythonConsoleDock",
            "terminal",
        )

        self.console_dock.hide()

        # --------------------------------------------------------------
        # Status bar
        # --------------------------------------------------------------

        self.status = QStatusBar()

        self.setStatusBar(
            self.status
        )

        self.status_title = QLabel(
            self._t(
                "app.title_version",
                "QGIS Python IDE Pro 1.0.0",
            )
        )

        self.status.addWidget(
            self.status_title
        )

        self.progress = QProgressBar()

        self.progress.setRange(
            0,
            100,
        )

        self.progress.setMaximumWidth(
            230
        )

        self.progress.setTextVisible(
            True
        )

        self.progress.hide()

        self.status.addPermanentWidget(
            self.progress
        )

        self.status_msg = QLabel(
            self._t(
                "status.ready",
                "Pronto",
            )
        )

        self.status.addPermanentWidget(
            self.status_msg
        )


    def _open_documents(self) -> list[EditorTab]:
        documents: list[EditorTab] = []

        for index in range(self.tabs.count()):
            widget = self.tabs.widget(index)

            if isinstance(widget, EditorTab):
                documents.append(widget)

        return documents

    def _current_document(self) -> EditorTab | None:
        widget = self.tabs.currentWidget()

        if isinstance(widget, EditorTab):
            return widget

        return None

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _make_action(
        self,
        command_id,
        title,
        callback,
        shortcut=None,
        icon=None,
        category="Generale",
    ):
        if not callable(callback):
            raise TypeError(
                f"Il callback dell'azione '{command_id}' non è chiamabile."
            )

        translated_title = self._t(
            f"action.{command_id}",
            title,
        )

        action = QAction(
            icon if isinstance(icon, QIcon) else self.icon(icon),
            translated_title,
            self,
        )

        if shortcut:
            action.setShortcut(shortcut)

        action.triggered.connect(callback)

        self.commands.add(
            command_id,
            title,
            callback,
            category,
        )

        if not hasattr(self, "_actions"):
            self._actions = {}

        self._actions[command_id] = action

        return action

    def _build_actions(self):
        A = self._make_action

        # --------------------------------------------------------------
        # File
        # --------------------------------------------------------------

        self.act_new = A(
            "new",
            "Nuovo Python",
            self._new_python,
            "Ctrl+N",
            "new",
            self._t("menu.file", "File"),
        )

        self.act_new_md = A(
            "newMarkdown",
            "Nuovo Markdown",
            self._new_markdown,
            None,
            "markdown",
            self._t("menu.file", "File"),
        )

        self.act_new_file = A(
            "newFile",
            "Nuovo file…",
            self._new_file,
            None,
            "new",
            self._t("menu.file", "File"),
        )

        self.act_open = A(
            "open",
            "Apri file…",
            self._open,
            "Ctrl+O",
            "open",
            self._t("menu.file", "File"),
        )

        self.act_new_project = A(
            "newProject",
            "Nuovo progetto",
            self._new_project,
            "Ctrl+Shift+N",
            "project",
            self._t("menu.project", "Progetto"),
        )

        self.act_open_project = A(
            "openProject",
            "Apri progetto plugin…",
            self._open_project_folder,
            "Ctrl+Shift+O",
            "project",
            self._t("menu.project", "Progetto"),
        )

        self.act_reload_project = A(
            "reloadProjectFiles",
            "Ricarica file del progetto",
            self._reload_project_files,
            None,
            "refresh",
            self._t("menu.project", "Progetto"),
        )

        self.act_save = A(
            "save",
            "Salva",
            self._save,
            "Ctrl+S",
            "save",
            self._t("menu.file", "File"),
        )

        self.act_saveall = A(
            "saveAll",
            "Salva tutto",
            self._save_all,
            "Ctrl+Shift+S",
            "save_all",
            self._t("menu.file", "File"),
        )

        self.act_saveas = A(
            "saveAs",
            "Salva con nome…",
            self._save_as,
            None,
            "save",
            self._t("menu.file", "File"),
        )

        self.act_close = A(
            "close",
            "Chiudi scheda",
            lambda: self._close_tab(
                self.tabs.currentIndex()
            ),
            "Ctrl+W",
            "close",
            self._t("menu.file", "File"),
        )

        self.act_close_project = A(
            "closeProject",
            "Chiudi progetto",
            self._close_project,
            "Ctrl+Shift+W",
            "close",
            self._t("menu.project", "Progetto"),
        )

        # --------------------------------------------------------------
        # Markdown
        # --------------------------------------------------------------

        self.act_markdown_preview = A(
            "markdownPreview",
            "Anteprima Markdown",
            self._toggle_markdown_preview,
            None,
            "preview",
            self._t("menu.markdown", "Markdown"),
        )

        # --------------------------------------------------------------
        # Edit / Code
        # --------------------------------------------------------------

        self.act_undo = A(
            "undo",
            "Annulla",
            self._undo,
            "Ctrl+Z",
            None,
            self._t("menu.edit", "Modifica"),
        )

        self.act_redo = A(
            "redo",
            "Ripeti",
            self._redo,
            "Ctrl+Y",
            None,
            self._t("menu.edit", "Modifica"),
        )

        self.act_find = A(
            "find",
            "Trova / Sostituisci",
            self._show_find_replace,
            "Ctrl+F",
            "search",
            self._t("menu.edit", "Modifica"),
        )

        self.act_comment = A(
            "comment",
            "Commenta righe selezionate",
            self._comment,
            "Ctrl+/",
            "comment",
            self._t("menu.code", "Codice"),
        )

        self.act_uncomment = A(
            "uncomment",
            "Decommenta righe selezionate",
            self._uncomment,
            "Ctrl+Shift+/",
            "uncomment",
            self._t("menu.code", "Codice"),
        )

        self.act_format = A(
            "format",
            "Formatta documento",
            self._format,
            "Ctrl+Shift+F",
            "format",
            self._t("menu.code", "Codice"),
        )

        self.act_trim = A(
            "trim",
            "Elimina spazi vuoti",
            self._trim,
            "Ctrl+Shift+W",
            None,
            self._t("menu.code", "Codice"),
        )

        self.act_complete = A(
            "completeLine",
            "Completa codice della riga",
            self._complete_line,
            "Ctrl+Space",
            "quickfix",
            self._t("menu.code", "Codice"),
        )

        # --------------------------------------------------------------
        # Run
        # --------------------------------------------------------------

        self.act_run = A(
            "run",
            "Esegui in QGIS",
            self._run,
            "F5",
            "run",
            self._t("menu.run", "Esegui"),
        )

        self.act_run_ext = A(
            "runExternal",
            "Esegui esterno",
            self._run_external,
            None,
            "terminal",
            self._t("menu.run", "Esegui"),
        )

        self.act_run_sel = A(
            "runSelection",
            "Esegui selezione",
            self._run_selection,
            "F6",
            "run",
            self._t("menu.run", "Esegui"),
        )

        self.act_run_block = A(
            "runBlock",
            "Esegui blocco corrente",
            self._run_block,
            None,
            "run",
            self._t("menu.run", "Esegui"),
        )

        self.act_stop = A(
            "stop",
            "Interrompi processo",
            self._stop,
            "Shift+F5",
            "stop",
            self._t("menu.run", "Esegui"),
        )

        # --------------------------------------------------------------
        # Analyze
        # --------------------------------------------------------------

        self.act_check = A(
            "check",
            "Controlla sintassi",
            self._check,
            "F7",
            "check",
            self._t("menu.analyze", "Analizza"),
        )

        self.act_analyze = A(
            "analyze",
            "Analizza codice e PyQGIS",
            self._check,
            None,
            "check",
            self._t("menu.analyze", "Analizza"),
        )

        self.act_fix = A(
            "quickFix",
            "Quick Fix",
            self._quick_fix,
            "Alt+Enter",
            "quickfix",
            self._t("menu.analyze", "Analizza"),
        )

        self.act_refresh_api = A(
            "refreshApi",
            "Aggiorna indice API QGIS",
            self._refresh_api,
            None,
            "refresh",
            self._t("menu.analyze", "Analizza"),
        )

        # --------------------------------------------------------------
        # Tools
        # --------------------------------------------------------------

        self.act_designer = A(
            "designer",
            "Apri Qt Designer",
            self._designer,
            None,
            "designer",
            self._t("menu.tools", "Strumenti"),
        )

        self.act_compile = A(
            "compileUI",
            "Converti UI → Python",
            self._compile_ui,
            None,
            "ui",
            self._t("menu.tools", "Strumenti"),
        )

        self.act_preview = A(
            "previewUI",
            "Anteprima UI",
            self._preview_ui,
            None,
            "preview",
            self._t("menu.tools", "Strumenti"),
        )

        self.act_snippets = A(
            "snippets",
            "Snippet",
            self._snippet_menu,
            None,
            "plugin",
            self._t("menu.tools", "Strumenti"),
        )

        self.act_wizard = A(
            "wizard",
            "Wizard plugin QGIS 4",
            self._plugin_wizard,
            None,
            "plugin",
            self._t("menu.tools", "Strumenti"),
        )

        self.act_palette = A(
            "palette",
            "Command Palette",
            self._command_palette,
            "Ctrl+Shift+P",
            "palette",
            self._t("menu.tools", "Strumenti"),
        )

        self.act_console = A(
            "console",
            "Console Python QGIS",
            self._toggle_console,
            "Ctrl+Alt+C",
            "terminal",
            self._t("menu.tools", "Strumenti"),
        )
        self.act_reload_api = A(
            "reloadApi",
            "Ricarica librerie e API QGIS",
            self._reload_qgis_runtime,
            None,
            "refresh",
            self._t("menu.tools", "Strumenti"),
        )
        self.act_self_check = A(
            "selfCheck",
            "Verifica integrità plugin",
            self._self_check,
            None,
            "check",
            self._t("menu.analyze", "Analizza"),
        )

        # --------------------------------------------------------------
        # Estensioni (sottoplugin)
        # --------------------------------------------------------------

        self.act_ext_reload = A(
            "extReload",
            "Ricarica estensioni",
            self._reload_extensions,
            None,
            "refresh",
            self._t("menu.extensions", "Estensioni"),
        )

        self.act_ext_create = A(
            "extCreate",
            "Crea estensione (sottoplugin)…",
            self._create_extension_wizard,
            None,
            "plugin",
            self._t("menu.extensions", "Estensioni"),
        )

        self.act_ext_guide = A(
            "extGuide",
            "Guida alle estensioni",
            self._extensions_guide,
            None,
            "help",
            self._t("menu.extensions", "Estensioni"),
        )

        # --------------------------------------------------------------
        # Real QMenus
        #
        # IMPORTANT:
        # Every variable in "menus" below is explicitly a QMenu.
        # This prevents a string from being passed to menu.icon().
        # --------------------------------------------------------------

        menubar = self.menuBar()
        menubar.setNativeMenuBar(False)
        menubar.setVisible(False)

        def create_menu(title, icon_name):
            menu = QMenu(title, menubar)
            menu.setIcon(self.icon(icon_name))
            menubar.addMenu(menu)
            return menu

        project_menu = create_menu(
            self._t("menu.project", "Progetto"),
            "project",
        )

        self.act_save_project = self._make_action(
            "saveProject",
            "Salva progetto",
            self._save_project,
            None,
            "save",
            self._t("menu.project", "Progetto"),
        )

        project_menu.addActions(
            [
                self.act_new_project,
                self.act_open_project,
                self.act_reload_project,
                self.act_save_project,
                self.act_close_project,
            ]
        )

        project_menu.addSeparator()
        project_menu.addAction(
            self.project_dock.toggleViewAction()
        )

        file_menu = create_menu(
            self._t("menu.file", "File"),
            "folder",
        )

        file_menu.addActions(
            [
                self.act_new,
                self.act_new_md,
                self.act_new_file,
                self.act_open,
                self.act_save,
                self.act_saveall,
                self.act_saveas,
                self.act_close,
            ]
        )

        markdown_menu = create_menu(
            self._t("menu.markdown", "Markdown"),
            "markdown",
        )

        markdown_menu.addAction(
            self.act_markdown_preview
        )

        edit_menu = create_menu(
            self._t("menu.edit", "Modifica"),
            "edit",
        )

        edit_menu.addActions(
            [
                self.act_undo,
                self.act_redo,
                self.act_find,
            ]
        )

        edit_menu.addSeparator()

        edit_menu.addActions(
            [
                self.act_comment,
                self.act_uncomment,
            ]
        )

        code_menu = create_menu(
            self._t("menu.code", "Codice"),
            "code",
        )

        code_menu.addActions(
            [
                self.act_complete,
                self.act_format,
                self.act_trim,
            ]
        )

        run_menu = create_menu(
            self._t("menu.run", "Esegui"),
            "run",
        )

        run_menu.addActions(
            [
                self.act_run,
                self.act_run_ext,
                self.act_run_sel,
                self.act_run_block,
                self.act_stop,
            ]
        )

        analyze_menu = create_menu(
            self._t("menu.analyze", "Analizza"),
            "check",
        )

        analyze_menu.addActions(
            [
                self.act_check,
                self.act_analyze,
                self.act_fix,
                self.act_refresh_api,
                self.act_self_check,
            ]
        )

        tools_menu = create_menu(
            self._t("menu.tools", "Strumenti"),
            "tools",
        )

        self._tools_menu = tools_menu

        tools_menu.addActions(
            [
                self.act_designer,
                self.act_compile,
                self.act_preview,
                self.act_snippets,
                self.act_wizard,
                self.act_palette,
                self.act_console,
                self.act_reload_api,
            ]
        )

        extensions_menu = create_menu(
            self._t("menu.extensions", "Estensioni"),
            "plugin",
        )

        self._extensions_menu = extensions_menu

        extensions_menu.addActions(
            [
                self.act_ext_reload,
                self.act_ext_create,
                self.act_ext_guide,
            ]
        )

        view_menu = create_menu(
            self._t("menu.view", "Visualizza"),
            "view",
        )

        self._view_menu = view_menu

        view_menu.addActions(
            [
                self.project_dock.toggleViewAction(),
                self.diag_dock.toggleViewAction(),
                self.api_dock.toggleViewAction(),
                self.log_dock.toggleViewAction(),
                self.console_dock.toggleViewAction(),
                self.find_replace_dock.toggleViewAction(),
            ]
        )
        view_menu.addSeparator()
        # Disposizione persistente dei pannelli: queste azioni restano solo nel menu.
        self.act_save_dock_layout = self._make_action(
            "saveDockLayout", "Salva disposizione pannelli",
            self._save_dock_layout, icon="layout-save",
            category=self._t("menu.view", "Visualizza"),
        )
        self.act_reset_dock_layout = self._make_action(
            "resetDockLayout", "Ripristina disposizione originale",
            self._reset_dock_layout, icon="layout-reset",
            category=self._t("menu.view", "Visualizza"),
        )
        view_menu.addSeparator()
        view_menu.addAction(self.act_save_dock_layout)
        view_menu.addAction(self.act_reset_dock_layout)

        language_menu = QMenu(
            self._t("menu.language", "Lingua"),
            view_menu,
        )

        language_menu.setIcon(
            self.icon("language")
        )

        view_menu.addMenu(language_menu)
        self._language_menu = language_menu

        self._language_actions = QActionGroup(self)
        self._language_actions.setExclusive(True)

        for language_code, label in [
            ("auto", self._t("ui.language_auto", "Automatico")),
            ("it", "Italiano"),
            ("en", "English"),
            ("de", "Deutsch"),
            ("fr", "Français"),
            ("es", "Español"),
        ]:
            action = QAction(
                label,
                self,
            )

            action.setCheckable(True)
            action.setData(language_code)

            action.triggered.connect(
                lambda checked, code=language_code:
                    self._set_language(code)
            )

            self._language_actions.addAction(
                action
            )

            language_menu.addAction(
                action
            )

        self._language_action_map = {a.data(): a for a in self._language_actions.actions()}

        help_menu = create_menu(
            self._t("menu.help", "Aiuto"),
            "help",
        )

        docs_action = self._make_action(
            "docs",
            "Documentazione PyQGIS",
            lambda: self._open_url(
                "https://docs.qgis.org/4.0/en/docs/pyqgis_developer_cookbook/"
            ),
            "F1",
            "docs",
            "Aiuto",
        )

        help_menu.addAction(
            docs_action
        )

        # --------------------------------------------------------------
        # Visual menu strip
        # --------------------------------------------------------------

        menu_strip = QToolBar(
            "Menu principale",
            self,
        )

        menu_strip.setObjectName(
            "MainMenuStrip"
        )

        menu_strip.setMovable(False)
        menu_strip.setFloatable(False)

        menu_strip.setIconSize(
            QSize(18, 18)
        )

        menu_strip.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonTextBesideIcon
        )

        menu_strip.setStyleSheet(
            """
            QToolButton {
                padding: 6px 11px;
                font-weight: 600;
            }

            QToolButton::menu-indicator {
                image: none;
                width: 0;
            }

            QToolButton:hover {
                background: rgba(80, 120, 180, 0.14);
            }
            """
        )

        # IMPORTANT:
        # This list contains only QMenu objects.
        menus = [
            project_menu,
            file_menu,
            markdown_menu,
            edit_menu,
            code_menu,
            run_menu,
            analyze_menu,
            tools_menu,
            extensions_menu,
            view_menu,
            help_menu,
        ]

        self._top_menus = menus
        self._menu_keys = (
            "project", "file", "markdown", "edit", "code",
            "run", "analyze", "tools", "extensions", "view",
            "help",
        )

        self._menu_buttons = []
        for qmenu in menus:

            if not isinstance(qmenu, QMenu):
                continue

            button = QToolButton(
                menu_strip
            )

            button.setText(
                qmenu.title()
            )

            button.setIcon(
                qmenu.icon()
            )

            button.setMenu(
                qmenu
            )

            button.setPopupMode(
                QToolButton.ToolButtonPopupMode.InstantPopup
            )

            button.setToolButtonStyle(
                Qt.ToolButtonStyle.ToolButtonTextBesideIcon
            )

            button.setMinimumWidth(
                menu_strip.fontMetrics().horizontalAdvance(
                    qmenu.title()
                ) + 54
            )

            button.setToolTip(
                qmenu.title()
            )

            menu_strip.addWidget(
                button
            )
            self._menu_buttons.append(button)

        self.addToolBar(
            Qt.ToolBarArea.TopToolBarArea,
            menu_strip,
        )

        # --------------------------------------------------------------
        # Main toolbar
        # --------------------------------------------------------------

        bar = QToolBar(
            self._t("ui.main_toolbar", "Azioni principali"),
            self,
        )

        bar.setObjectName(
            "MainToolbar"
        )

        bar.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonTextBesideIcon
        )

        bar.setIconSize(
            QSize(20, 20)
        )

        bar.setMovable(True)
        bar.setFloatable(True)

        self.addToolBar(
            Qt.ToolBarArea.TopToolBarArea,
            bar,
        )

        groups = [
            (
                "File",
                [
                    self.act_new,
                    self.act_open,
                    self.act_save,
                    self.act_saveall,
                ],
            ),
            (
                "Esegui",
                [
                    self.act_run,
                    self.act_run_sel,
                    self.act_run_block,
                    self.act_stop,
                ],
            ),
            (
                "Codice",
                [
                    self.act_complete,
                    self.act_comment,
                    self.act_uncomment,
                    self.act_format,
                    self.act_trim,
                ],
            ),
            (
                "Analisi",
                [
                    self.act_check,
                    self.act_fix,
                    self.act_refresh_api,
                ],
            ),
            (
                "Qt / Plugin",
                [
                    self.act_designer,
                    self.act_compile,
                    self.act_preview,
                    self.act_wizard,
                ],
            ),
            (
                "Strumenti",
                [
                    self.act_snippets,
                    self.act_palette,
                ],
            ),
        ]

        for group_index, (label, actions) in enumerate(groups):

            if group_index:
                bar.addSeparator()

            for action in actions:
                bar.addAction(action)

        # --------------------------------------------------------------
        # Search toolbar
        # --------------------------------------------------------------

        searchbar = QToolBar(
            self._t("ui.search_toolbar", "Ricerca"),
            self,
        )

        searchbar.setObjectName(
            "SearchToolbar"
        )

        searchbar.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonTextBesideIcon
        )

        searchbar.setIconSize(
            QSize(18, 18)
        )

        self.project_search_label = QLabel(
            self._t("ui.project_search", "Search project")
        )
        searchbar.addWidget(self.project_search_label)

        self.global_search = QLineEdit()

        self.global_search.setPlaceholderText(
            self._t("ui.global_search", "Cerca file, simboli o testo…")
        )

        self.global_search.setMinimumWidth(
            300
        )

        self.global_search.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )

        searchbar.addWidget(
            self.global_search
        )

        self.project_search_action = searchbar.addAction(
            self.icon("search"),
            self._t("ui.project_search_button", "Search project"),
            self._project_search,
        )

        self.addToolBar(
            Qt.ToolBarArea.TopToolBarArea,
            searchbar,
        )

        self._fit_menu_widths(
            menubar
        )

        # --------------------------------------------------------------
        # Keep toolbar labels visible
        # --------------------------------------------------------------

        for action in bar.actions():

            widget = bar.widgetForAction(
                action
            )

            if widget is not None:

                widget.setMinimumWidth(
                    max(
                        widget.minimumWidth(),
                        widget.fontMetrics().horizontalAdvance(
                            action.text()
                        ) + 48,
                    )
                )

                widget.setSizePolicy(
                    QSizePolicy.Policy.Preferred,
                    QSizePolicy.Policy.Preferred,
                )

    def _fit_menu_widths(self, menubar):
        font_metrics = menubar.fontMetrics()

        for menu in menubar.findChildren(QMenu):

            width = 300

            for action in menu.actions():

                if action.isSeparator():
                    continue

                text = action.text().replace(
                    "&",
                    "",
                )

                width = max(
                    width,
                    font_metrics.horizontalAdvance(
                        text
                    ) + 92,
                )

                submenu = action.menu()

                if submenu:
                    self._fit_menu_widths(
                        submenu
                    )

                    width = max(
                        width,
                        submenu.minimumWidth() + 18,
                    )

            menu.setMinimumWidth(
                width
            )

    # ------------------------------------------------------------------
    # Extensions
    # ------------------------------------------------------------------

    def _load_extensions_ui(self):
        target_menu = getattr(
            self,
            "_extensions_menu",
            None,
        )

        if target_menu is None:
            for menu in self.menuBar().findChildren(QMenu):

                if menu.title() == self._t(
                    "menu.extensions", "Estensioni"
                ):
                    target_menu = menu
                    break

        if target_menu is None:
            return

        # Rimuove le azioni iniettate in precedenza: evita duplicati
        # a ogni "Ricarica estensioni".
        for action in getattr(self, "_extension_injected", []):
            target_menu.removeAction(action)
        self._extension_injected = []

        has_actions = any(
            getattr(extension, "actions", None)
            for extension in self.extensions.extensions
        )

        if has_actions and target_menu.actions():
            self._extension_injected.append(
                target_menu.addSeparator()
            )

        for extension in self.extensions.extensions:

            try:

                if hasattr(
                    extension.module,
                    "register",
                ):
                    extension.module.register(
                        self
                    )

                for action in extension.actions:

                    if isinstance(
                        action,
                        QAction,
                    ):
                        target_menu.addAction(
                            action
                        )
                        self._extension_injected.append(
                            action
                        )

            except Exception as error:

                self.log.append(
                    f"Estensione {extension.name}: {error}",
                    "WARNING",
                )

    # ------------------------------------------------------------------
    # Estensioni (sottoplugin)
    # ------------------------------------------------------------------

    def _reload_extensions(self):
        """Rilegge le estensioni dal disco e aggiorna il menu.

        Le azioni vecchie vengono rimosse da _load_extensions_ui, cosi'
        le voci di menu non vengono mai duplicate."""
        self.extensions.discover()
        self._load_extensions_ui()

        loaded = len(self.extensions.extensions)
        if self.extensions.errors:
            for name, error in self.extensions.errors.items():
                self.log.append(
                    f"Estensione {name}: {error}",
                    "WARNING",
                )

        self.status_msg.setText(
            self._t(
                "status.extensions_reloaded",
                "Estensioni ricaricate: {count}",
            ).replace("{count}", str(loaded))
        )

    def _create_extension_wizard(self):
        """Genera una nuova estensione (sottoplugin) dell'IDE.

        Crea la cartella extensions/<nome>/extension.py dentro la
        cartella del plugin, con un modello bilingue (IT/EN) pronto
        all'uso, poi ricarica le estensioni e apre il file generato.
        """
        name, ok = QInputDialog.getText(
            self,
            self._t("ext.create_title", "Crea estensione"),
            self._t(
                "ext.create_prompt",
                "Nome della nuova estensione (sottoplugin):",
            ),
        )

        if not ok or not name.strip():
            return

        module = self._wizard_safe_module_name(name)
        display = name.strip()

        root = os.path.dirname(
            os.path.dirname(__file__)
        )
        ext_dir = os.path.join(
            root,
            "extensions",
            module,
        )
        os.makedirs(
            ext_dir,
            exist_ok=True,
        )

        entry = os.path.join(
            ext_dir,
            "extension.py",
        )

        if os.path.exists(entry):
            QMessageBox.warning(
                self,
                self._t("ext.create_title", "Crea estensione"),
                self._t(
                    "ext.exists",
                    "Esiste già un'estensione con questo nome.",
                ),
            )
            return

        class_name = self._wizard_class_name(module) + "Extension"

        template = (
            '"""Estensione (sottoplugin) per QGIS Python IDE Pro.\n\n'
            'Documentazione: menu Estensioni → Guida alle estensioni.\n'
            'Structure: extensions/<nome>/extension.py con\n'
            'create_extension() che restituisce un oggetto con\n'
            '"name" e "actions"; opzionale register(window).\n"""\n\n'
            'from qgis.PyQt.QtGui import QAction\n\n\n'
            'MESSAGES = {\n'
            '    "it": {\n'
            f'        "menu": "{display}",\n'
            '        "hello": "Estensione caricata",\n'
            '        "hello_msg": "Funzionalità del sottoplugin eseguita.",\n'
            '    },\n'
            '    "en": {\n'
            f'        "menu": "{display}",\n'
            '        "hello": "Extension loaded",\n'
            '        "hello_msg": "Sub-plugin feature executed.",\n'
            '    },\n'
            '}\n\n\n'
            f'class {class_name}:\n'
            '    """Sottoplugin con azioni bilingui IT/EN."""\n\n'
            '    def __init__(self):\n'
            '        self.name = "' + display.replace('"', "") + '"\n'
            '        self._window = None\n'
            '        self.actions = []\n\n'
            '    def _lang(self):\n'
            '        """Lingua corrente: quella dell\'IDE se disponibile."""\n'
            '        if self._window is not None:\n'
            '            try:\n'
            '                code = self._window.i18n.code()\n'
            '                if code in MESSAGES:\n'
            '                    return code\n'
            '            except Exception:\n'
            '                pass\n'
            '        from qgis.PyQt.QtCore import QLocale\n\n'
            '        name = QLocale.system().name()\n'
            '        return "it" if name.startswith("it") else "en"\n\n'
            '    def tr(self, key):\n'
            '        lang = self._lang()\n'
            '        return MESSAGES.get(lang, MESSAGES["en"]).get(\n'
            '            key, key\n'
            '        )\n\n'
            '    def _run(self):\n'
            '        if self._window is None:\n'
            '            return\n'
            '        self._window.iface.messageBar().pushInfo(\n'
            '            self.tr("hello"), self.tr("hello_msg")\n'
            '        )\n\n'
            '    def register(self, window):\n'
            '        """Chiamato dall\'IDE con la finestra principale."""\n'
            '        self._window = window\n'
            '        action = QAction(\n'
            '            self.tr("menu"), window\n'
            '        )\n'
            '        action.triggered.connect(self._run)\n'
            '        self.actions.append(action)\n\n\n'
            'def create_extension():\n'
            f'    return {class_name}()\n'
        )

        with open(
            entry,
            "w",
            encoding="utf-8",
        ) as handle:
            handle.write(template)

        self._reload_extensions()

        try:
            self._open_path(entry)
        except Exception:  # nosec B110 -- guardia difensiva UI
            pass

        self.log.append(
            f"Estensione creata: {entry}",
            "INFO",
        )

    def _extensions_guide(self):
        """Guida alle estensioni nella lingua corrente dell'IDE.

        Il contenuto HTML e' nelle traduzioni (chiave "ext.guide_html"
        nei file translations/*.json): al cambio lingua cambia anche
        la guida, senza modifiche al codice.
        """
        dialog = QDialog(self)
        dialog.setWindowTitle(
            self._t(
                "ext.guide_title",
                "Guida alle estensioni (sottoplugin)",
            )
        )
        dialog.resize(760, 640)

        layout = QVBoxLayout(dialog)

        view = QTextBrowser(dialog)

        # Guida localizzata: il fallback bilingue IT/EN copre il caso
        # di chiave mancante nelle traduzioni.
        view.setHtml(
            self._t(
                "ext.guide_html",
                self._extensions_guide_fallback_html(),
            )
        )

        try:
            from qgis.PyQt.QtGui import QFontDatabase

            view.setFont(
                QFontDatabase.systemFont(
                    QFontDatabase.SystemFont.FixedFont
                )
            )
        except Exception:  # nosec B110 -- guardia difensiva UI
            pass

        layout.addWidget(view, 1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Close,
            parent=dialog,
        )
        buttons.rejected.connect(dialog.reject)
        buttons.accepted.connect(dialog.accept)
        layout.addWidget(buttons)

        dialog.exec()

    @staticmethod
    def _extensions_guide_fallback_html():
        """Fallback bilingue IT/EN se la chiave tradotta manca."""
        return """
<h2>Guida alle estensioni (sottoplugin)</h2>
<ol>
<li><b>Estensioni → Crea estensione (sottoplugin)…</b>: inserisci il nome.</li>
<li>Il wizard genera <code>extensions/&lt;nome&gt;/extension.py</code>
dentro la cartella del plugin e lo apre nell'IDE.</li>
<li>Modifica il file, poi <b>Estensioni → Ricarica estensioni</b>: la
voce di menu appare subito senza riavviare QGIS.</li>
</ol>
<p>Il file deve esporre <code>create_extension()</code> (oggetto con
<code>name</code> e <code>actions</code>) e opzionalmente
<code>register(window)</code> per accedere a window.iface, window.tabs,
window.i18n e window.log. Compatibilità Qt6/QGIS 4: solo import da
<code>qgis.PyQt</code>.</p>
<hr>
<h2>Extensions guide (sub-plugins)</h2>
<ol>
<li><b>Extensions → Create extension (sub-plugin)…</b>: enter a name.</li>
<li>The wizard generates <code>extensions/&lt;name&gt;/extension.py</code>
inside the plugin folder and opens it in the IDE.</li>
<li>Edit the file, then <b>Extensions → Reload extensions</b>: the menu
entry appears immediately without restarting QGIS.</li>
</ol>
<p>The file must expose <code>create_extension()</code> (object with
<code>name</code> and <code>actions</code>) and optionally
<code>register(window)</code> to access window.iface, window.tabs,
window.i18n and window.log. Qt6/QGIS 4 compatibility: import only from
<code>qgis.PyQt</code>.</p>
"""

    # ------------------------------------------------------------------
    # Language
    # ------------------------------------------------------------------

    def _set_language(self, code):
        self.i18n.set_language(code)

        self.status_msg.setText(
            f"Lingua: {self.i18n.code()}"
        )

        self._retranslate_runtime()

    def _retranslate_runtime(self):
        self.setWindowTitle(
            f"QGIS Python IDE Pro 1.0.0 — {self.i18n.code()}"
        )
        for command_id, action in getattr(self, "_actions", {}).items():
            current = self.commands.get(command_id)
            if current:
                action.setText(self._t(f"action.{command_id}", current.title))
        for menu, key in zip(getattr(self, "_top_menus", ()), getattr(self, "_menu_keys", ())):
            menu.setTitle(self._t(f"menu.{key}", menu.title()))
        if hasattr(self, "_language_menu"):
            self._language_menu.setTitle(self._t("menu.language", "Lingua"))
        auto_action = getattr(self, "_language_action_map", {}).get("auto")
        if auto_action is not None:
            auto_action.setText(self._t("ui.language_auto", "Automatico"))
        for button, menu in zip(getattr(self, "_menu_buttons", ()), getattr(self, "_top_menus", ())):
            button.setText(menu.title())
            button.setToolTip(menu.title())
        if hasattr(self, "console_dock"):
            self.console_dock.setWindowTitle(self._t("dock.console", "Python Console"))
        if hasattr(self, "console"):
            self.console.retranslate(self._t)
        if hasattr(self, "log"):
            self.log.retranslate(self._t)
        if hasattr(self, "find_replace"):
            self.find_replace.retranslate(self._t)
        if hasattr(self, "find_replace_dock"):
            self.find_replace_dock.setWindowTitle(
                self._t(
                    "dock.find_replace",
                    "Trova e sostituisci",
                )
            )
        for dock, key, default in (
            (getattr(self, "project_dock", None), "dock.project", "Esplora progetto"),
            (getattr(self, "diag_dock", None), "dock.diagnostics", "Diagnostica / Quick Fix"),
            (getattr(self, "api_dock", None), "dock.api", "Documentazione API / PyQGIS"),
        ):
            if dock is not None:
                dock.setWindowTitle(self._t(key, default))
        if hasattr(self, "diag"):
            self.diag.setHeaderLabels([
                self._t("ui.line", "Riga"),
                self._t("ui.column", "Col."),
                self._t("ui.level", "Livello"),
                self._t("ui.diagnostic", "Diagnostica"),
                self._t("ui.code", "Codice"),
            ])
        if hasattr(self, "project_search_label"):
            self.project_search_label.setText(self._t("ui.project_search", "Search project"))
        if hasattr(self, "project_search_action"):
            self.project_search_action.setText(self._t("ui.project_search_button", "Search project"))
            self.project_search_action.setToolTip(self._t("ui.project_search_button", "Search project"))
        if hasattr(self, "global_search"):
            self.global_search.setPlaceholderText(self._t("ui.global_search", "Search files, symbols or text…"))

        # Retraduci anche le estensioni caricate: ogni modulo può
        # esporre retranslate() che aggiorna testi e icone delle azioni.
        for extension in getattr(self.extensions, "extensions", []):
            try:
                retranslate = getattr(extension.module, "retranslate", None)

                if callable(retranslate):
                    retranslate()
            except Exception:  # nosec B110 -- guardia difensiva UI
                pass
    # ------------------------------------------------------------------
    # Restore / Close
    # ------------------------------------------------------------------

    def _restore(self):
        # Registra una disposizione originale stabile una sola volta.
        if not self.settings.contains("original_dock_state"):
            self.settings.set("original_dock_state", self.saveState(220))
            self.settings.sync()
        saved_docks = self.settings.get("dock_state", None)
        if saved_docks:
            try:
                self.restoreState(saved_docks, 220)
            except (TypeError, RuntimeError) as exc:
                self.log.append(
                    f"Impossibile ripristinare la disposizione pannelli: {exc}",
                    "WARNING",
                )
        geometry = self.settings.geometry()
        if geometry:
            self.restoreGeometry(geometry)

    def _save_dock_layout(self):
        self.settings.set("dock_state", self.saveState(220))
        self.settings.sync()
        self.status_msg.setText(self._t("status.dock_saved", "Disposizione pannelli salvata"))

    def _reset_dock_layout(self):
        answer = QMessageBox.question(
            self,
            self._t("dialog.reset_docks_title", "Ripristina pannelli"),
            self._t("dialog.reset_docks_confirm", "Ripristinare la disposizione originale dei pannelli?"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        original = self.settings.get("original_dock_state", None)
        if original:
            self.restoreState(original, 220)
        self.settings.remove("dock_state")
        self.settings.sync()
        self.status_msg.setText(self._t("status.dock_reset", "Disposizione originale ripristinata"))

    def closeEvent(self, event):

        if not self._confirm_close_all():
            event.ignore()
            return

        self.settings.set_geometry(
            self.saveGeometry()
        )
        QSettings().setValue("QGIS_Python_IDE_Pro/panel_layout", self.saveState())
        QSettings().sync()

        event.accept()

    def _confirm_close_all(self):

        for index in range(
            self.tabs.count() - 1,
            -1,
            -1,
        ):

            if not self._close_tab(
                index,
                confirm=True,
            ):
                return False

        return True

    # ------------------------------------------------------------------
    # Tabs
    # ------------------------------------------------------------------

    def current(self):
        return self.tabs.currentWidget()

    def _new_python(self):
        tab = EditorTab(
            None,
            self,
            self.language,
            self._show_completion,
            self._show_documentation,
            self._t,
            self._format,
            self._check,
            self._comment,
            self._uncomment,
        )

        tab.set_text("")
        tab.suggested_name = "nuovo.py"

        self._add_tab(
            tab,
            "nuovo.py",
        )

    def _new_markdown(self) -> None:
        tab = EditorTab(
            None,
            self,
            self.language,
            self._show_completion,
            self._show_documentation,
            self._t,
            self._format,
            self._check,
            self._comment,
            self._uncomment,
            initial_suffix=".md",
        )

        tab.set_text("")
        tab.suggested_name = "README.md"

        self._add_tab(
            tab,
            "README.md",
        )

    def _toggle_markdown_preview(self) -> None:
        """Mostra/nasconde l'anteprima esclusivamente per documenti Markdown."""
        tab = self.tabs.currentWidget()
        if not isinstance(tab, EditorTab):
            return

        suffix = (
            os.path.splitext(tab.path)[1]
            if getattr(tab, "path", None)
            else self._tab_suffix(tab)
        ).lower()

        if suffix not in {".md", ".markdown"}:
            self.act_markdown_preview.setEnabled(False)
            return

        preview = getattr(tab, "preview", None)
        if preview is None:
            return

        if preview.isVisible():
            preview.hide()
            return

        tab.sync_markdown_preview()
        preview.show()

    def _tab_suffix(self, tab):
        suffix = str(getattr(tab, "file_suffix", "") or "").lower()
        if suffix:
            return suffix
        language = str(getattr(tab, "language", "")).lower()
        if language == "markdown":
            return ".md"
        if language == "python":
            return ".py"
        return ""

    def _on_current_tab_changed(self):
        self._refresh_title()
        action = getattr(self, "act_markdown_preview", None)
        tab = self.current()
        enabled = False
        if isinstance(tab, EditorTab):
            suffix = (
                os.path.splitext(tab.path)[1]
                if getattr(tab, "path", None)
                else self._tab_suffix(tab)
            ).lower()
            enabled = suffix in {".md", ".markdown"}
        if action is not None:
            action.setEnabled(enabled)

    def _new_file(self):
        name, ok = QInputDialog.getText(
            self,
            "Nuovo file",
            "Nome file (senza estensione):",
        )

        if not ok or not name.strip():
            return

        name = name.strip()
        extensions = [
            ".py", ".pyw", ".md", ".markdown", ".qss", ".css",
            ".txt", ".xml", ".ui", ".ts", ".ini", ".cfg",
            ".json", ".yaml", ".yml",
        ]

        # Se il nome contiene già un'estensione supportata, usala come
        # selezione iniziale invece di creare un doppione.
        base, typed_extension = os.path.splitext(name)
        typed_extension = typed_extension.lower()
        if typed_extension in extensions:
            name = base or "senza_nome"
            default_index = extensions.index(typed_extension)
        else:
            default_index = 0

        extension, ok = QInputDialog.getItem(
            self,
            "Nuovo file",
            "Estensione:",
            extensions,
            default_index,
            False,
        )

        if not ok or not extension:
            return

        filename = name + extension

        tab = EditorTab(
            None,
            self,
            self.language,
            self._show_completion,
            self._show_documentation,
            self._t,
            self._format,
            self._check,
            self._comment,
            self._uncomment,
            initial_suffix=extension,
        )
        tab.set_text("")
        tab.suggested_name = filename

        self._add_tab(
            tab,
            filename,
        )

    def _add_tab(self, tab, title):
        if tab is None:
            return

        path = getattr(tab, "path", None)

        if not title:
            title = (
                os.path.basename(path)
                if path
                else "Senza titolo"
            )

        index = self.tabs.addTab(
            tab,
            self.icon_for_file(path, tab),
            str(title),
        )

        self.tabs.setCurrentIndex(index)

        self._color_tab(
            index,
            path,
        )

    def icon_for_file(self, path, tab=None):
        if path:
            extension = os.path.splitext(path)[1].lower()
        else:
            extension = str(
                getattr(tab, "file_suffix", ".py") or ".py"
            ).lower()

        icons = {
            ".py": "plugin",
            ".pyw": "plugin",
            ".md": "markdown",
            ".qss": "qss",
            ".css": "qss",
            ".xml": "xml",
            ".ui": "ui",
            ".ts": "xml",
            ".txt": "text",
            ".json": "xml",
        }

        return self.icon(
            icons.get(
                extension,
                "text",
            )
        )

    def _color_tab(self, index, path):
        if not hasattr(self, "tabs") or self.tabs is None:
            return

        bar = self.tabs.tabBar()

        if index < 0 or index >= bar.count():
            return

        colors = {
            ".py": "#42a5f5",
            ".md": "#607dff",
            ".qss": "#ec407a",
            ".xml": "#ff7043",
            ".ui": "#00bfa5",
            ".ts": "#ab47bc",
            ".txt": "#90a4ae",
        }

        extension = os.path.splitext(
            str(path or "")
        )[1].lower()

        color = colors.get(
            extension,
            "#90a4ae",
        )

        bar.setTabTextColor(
            index,
            QColor(color),
        )

    # ------------------------------------------------------------------
    # Open / Project
    # ------------------------------------------------------------------

    def _open(self):

        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Apri file",
            self.settings.get(
                "last_dir",
                "",
            ),
            (
                "File supportati "
                "(*.py *.pyw *.md *.markdown *.qss *.css "
                "*.txt *.xml *.ui *.ts *.ini *.cfg *.json *.yaml *.yml)"
                ";;Tutti i file (*)"
            ),
        )

        for path in paths:
            self._open_path(path)

    def _open_path(self, path):

        for index in range(
            self.tabs.count()
        ):

            tab = self.tabs.widget(index)

            if tab.path == path:
                self.tabs.setCurrentIndex(
                    index
                )
                return

        try:

            with open(
                path,
                "r",
                encoding="utf-8",
            ) as file:
                text = file.read()

        except UnicodeDecodeError:

            with open(
                path,
                "r",
                encoding="latin-1",
            ) as file:
                text = file.read()

        tab = EditorTab(
            path,
            self,
            self.language,
            self._show_completion,
            self._show_documentation,
            self._t,
            self._format,
            self._check,
            self._comment,
            self._uncomment,
        )

        tab.set_text(text)

        self._add_tab(
            tab,
            os.path.basename(path),
        )

        self.settings.set(
            "last_dir",
            os.path.dirname(path),
        )

    def _new_project(self):
        from qgis.PyQt.QtWidgets import QInputDialog

        parent_folder = QFileDialog.getExistingDirectory(
            self,
            "Cartella del nuovo progetto",
            self.settings.get(
                "project_dir",
                "",
            ),
        )

        if not parent_folder:
            return

        name, ok = QInputDialog.getText(
            self,
            "Nuovo progetto",
            "Nome del progetto:",
        )

        if not ok:
            return

        name = name.strip()

        if not name:
            QMessageBox.warning(
                self,
                "Nuovo progetto",
                "Inserisci un nome valido per il progetto.",
            )
            return

        project_folder = os.path.join(
            parent_folder,
            name,
        )

        if os.path.exists(project_folder):
            QMessageBox.warning(
                self,
                "Nuovo progetto",
                f"La cartella '{name}' esiste già.",
            )
            return

        try:
            os.makedirs(project_folder)

            metadata_path = os.path.join(
                project_folder,
                "metadata.txt",
            )

            init_path = os.path.join(
                project_folder,
                "__init__.py",
            )

            main_path = os.path.join(
                project_folder,
                "main.py",
            )

            readme_path = os.path.join(
                project_folder,
                "README.md",
            )

            metadata = f"""[general]
name={name}
description=QGIS plugin {name}
version=1.0.0
qgisMinimumVersion=3.0
author=QGIS Python IDE
email=
about=Plugin creato con QGIS Python IDE
category=Plugins
"""

            init_code = """def classFactory(iface):
    from .main import MainPlugin
    return MainPlugin(iface)
"""

            main_code = f'''from qgis.PyQt.QtGui import QAction


class MainPlugin:

    def __init__(self, iface):
        self.iface = iface
        self.action = None

    def initGui(self):
        self.action = QAction(
            "{name}",
            self.iface.mainWindow(),
        )

        self.action.triggered.connect(
            self.run
        )

        self.iface.addPluginToMenu(
            "&{name}",
            self.action,
        )

        self.iface.addToolBarIcon(
            self.action,
        )

    def unload(self):
        if self.action is not None:
            self.iface.removePluginMenu(
                "&{name}",
                self.action,
            )

            self.iface.removeToolBarIcon(
                self.action,
            )

            self.action.deleteLater()
            self.action = None

    def run(self):
        self.iface.messageBar().pushInfo(
            "{name}",
            "Plugin in esecuzione.",
        )
'''

            readme = f"""# {name}

Plugin QGIS creato con QGIS Python IDE.

## Struttura

- `metadata.txt` — metadati del plugin
- `__init__.py` — factory del plugin
- `main.py` — codice principale
"""

            files = {
                metadata_path: metadata,
                init_path: init_code,
                main_path: main_code,
                readme_path: readme,
            }

            for path, content in files.items():
                with open(
                    path,
                    "w",
                    encoding="utf-8",
                ) as handle:
                    handle.write(content)

        except OSError as error:
            QMessageBox.critical(
                self,
                "Nuovo progetto",
                f"Impossibile creare il progetto:\n{error}",
            )
            return

        self.settings.set(
            "project_dir",
            project_folder,
        )
        self.project_root = project_folder

        self._populate_project(
            project_folder
        )

        self.status_msg.setText(
            f"Progetto: {project_folder}"
        )

        self._open_path(
            main_path
        )

    def _open_project_folder(self):
        folder = QFileDialog.getExistingDirectory(
            self,
            "Apri progetto plugin",
            self.settings.get(
                "project_dir",
                "",
            ),
        )

        if not folder:
            return

        self.settings.set(
            "project_dir",
            folder,
        )
        self.project_root = folder

        self._populate_project(
            folder
        )

        self.status_msg.setText(
            f"Progetto: {folder}"
        )

    def _reload_project_files(self):
        """Rilegge l'albero del progetto senza chiudere le schede aperte."""
        folder = str(getattr(self, "project_root", "") or "").strip()

        if not folder or not os.path.isdir(folder):
            QMessageBox.information(
                self,
                self._t("menu.project", "Progetto"),
                self._t("dialog.no_project_to_reload", "Nessun progetto aperto da ricaricare."),
            )
            return
        # Rientra il percorso in memoria anche se ripreso dai settings.
        self.project_root = folder
        self._populate_project(folder)
        self.status_msg.setText(
            self._t("status.project_reloaded", "File del progetto ricaricati")
        )

    def _populate_project(self, folder):

        self.project.clear()

        root = QTreeWidgetItem(
            [
                os.path.basename(folder)
                or folder
            ]
        )

        root.setData(
            0,
            Qt.ItemDataRole.UserRole,
            folder,
        )

        self.project.addTopLevelItem(
            root
        )

        self._walk_tree(
            root,
            folder,
            0,
        )

        root.setExpanded(True)

    def _walk_tree(
        self,
        parent,
        folder,
        depth,
    ):

        if depth > 5:
            return

        skip = {
            ".git",
            ".venv",
            "venv",
            "__pycache__",
            ".idea",
            ".qgis",
        }

        try:

            names = sorted(
                os.listdir(folder),
                key=lambda value: (
                    not os.path.isdir(
                        os.path.join(
                            folder,
                            value,
                        )
                    ),
                    value.lower(),
                ),
            )

        except OSError:
            return

        for name in names:

            if (
                name in skip
                or (
                    name.startswith(".")
                    and name not in {".gitignore"}
                )
            ):
                continue

            path = os.path.join(
                folder,
                name,
            )

            item = QTreeWidgetItem(
                [name]
            )

            item.setData(
                0,
                Qt.ItemDataRole.UserRole,
                path,
            )

            item.setIcon(
                0,
                self.icon(
                    "folder"
                    if os.path.isdir(path)
                    else "text"
                ),
            )

            parent.addChild(item)

            if os.path.isdir(path):
                self._walk_tree(
                    item,
                    path,
                    depth + 1,
                )

    def _project_open(self, item, column):

        path = item.data(
            0,
            Qt.ItemDataRole.UserRole,
        )

        if (
            path
            and os.path.isfile(path)
            and os.path.splitext(path)[1].lower()
            in EditorTab.SUPPORTED
        ):
            self._open_path(path)

    # ------------------------------------------------------------------
    # Save
    # ------------------------------------------------------------------

    def _save_project(self) -> bool:
        """Salva il progetto del plugin: scrive su disco TUTTI i file
        delle schede che contengono modifiche, non il progetto QGIS."""
        saved = 0
        failed = []

        for index in range(self.tabs.count()):
            tab = self.tabs.widget(index)

            if tab is None:
                continue

            try:
                is_modified = (
                    tab.is_modified()
                    if hasattr(tab, "is_modified")
                    else bool(getattr(tab, "modified", False))
                )

                if not is_modified:
                    continue

                if hasattr(tab, "save"):
                    if tab.save():
                        saved += 1
                    else:
                        failed.append(
                            getattr(tab, "path", None)
                            or f"Scheda {index + 1}"
                        )

            except Exception as error:
                failed.append(
                    f"{getattr(tab, 'path', 'scheda')}: {error}"
                )

        try:
            if getattr(self, "project_root", ""):
                self.settings.set(
                    "project_dir",
                    self.project_root,
                )
        except Exception:  # nosec B110 -- guardia difensiva UI
            pass

        if failed:
            self.log.append(
                "Salvataggio progetto — file non salvati: "
                + "; ".join(str(item) for item in failed),
                "WARNING",
            )

        if saved or not failed:
            self.status_msg.setText(
                self._t(
                    "status.project_saved_files",
                    "Progetto salvato: {count} file aggiornati",
                ).replace("{count}", str(saved))
            )
            return not failed

        self.status_msg.setText(
            self._t(
                "status.project_save_failed",
                "Salvataggio progetto non riuscito",
            )
        )
        return False

    def _save(self) -> bool:
        tab = self.current()

        if tab is None:
            return False

        if not tab.path:
            return self._save_as()

        try:
            saved = bool(tab.save())
        except Exception as error:
            QMessageBox.critical(
                self,
                "Salvataggio",
                f"Impossibile salvare il file.\n\n{error}",
            )
            self.log.append(
                f"Salvataggio fallito: {error}",
                "ERROR",
            )
            return False

        if not saved:
            return False

        self._refresh_title()
        self._project_search_status()

        self.status_msg.setText(
            f"Salvato: {os.path.basename(tab.path)}"
        )

        return True

    def _save_all(self) -> bool:
        saved_count = 0
        failed_count = 0

        for index in range(self.tabs.count()):
            tab = self.tabs.widget(index)

            if tab is None:
                continue

            if not tab.path:
                self.tabs.setCurrentIndex(index)

                if self._save_as():
                    saved_count += 1
                else:
                    failed_count += 1

                continue

            try:
                if tab.save():
                    saved_count += 1
                else:
                    failed_count += 1
            except Exception as error:
                failed_count += 1
                self.log.append(
                    f"Salvataggio fallito per "
                    f"{tab.path}: {error}",
                    "ERROR",
                )

        self._refresh_title()

        if failed_count:
            self.status_msg.setText(
                f"Salvati {saved_count} file, "
                f"{failed_count} con errore"
            )
        else:
            self.status_msg.setText(
                f"Tutti i file salvati ({saved_count})"
            )

        return failed_count == 0

    def _save_as(self) -> bool:
        tab = self.current()

        if tab is None:
            return False

        suggested = getattr(tab, "suggested_name", "")
        last_dir = self.settings.get(
            "last_dir",
            "",
        )
        default_path = tab.path or (
            os.path.join(last_dir, suggested)
            if suggested
            else last_dir
        )

        path, _ = QFileDialog.getSaveFileName(
            self,
            "Salva con nome",
            default_path,
            (
                "File supportati "
                "(*.py *.pyw *.md *.markdown *.qss *.css "
                "*.txt *.xml *.ui *.ts *.ini *.cfg *.json *.yaml *.yml)"
                ";;Tutti i file (*)"
            ),
        )

        if not path:
            return False

        try:
            if not tab.save(path):
                return False
            tab.file_suffix = os.path.splitext(path)[1].lower()
            if hasattr(tab, "preview"):
                tab.sync_markdown_preview()
        except Exception as error:
            QMessageBox.critical(
                self,
                "Salvataggio",
                f"Impossibile salvare il file.\n\n{error}",
            )
            self.log.append(
                f"Salvataggio con nome fallito: {error}",
                "ERROR",
            )
            return False

        index = self.tabs.currentIndex()

        if index >= 0:
            self.tabs.setTabText(
                index,
                os.path.basename(path),
            )

            self.tabs.setTabIcon(
                index,
                self.icon_for_file(path),
            )

            self._color_tab(
                index,
                path,
            )

        self.settings.set(
            "last_dir",
            os.path.dirname(os.path.abspath(path)),
        )

        self._refresh_title()
        self.status_msg.setText(
            f"Salvato: {os.path.basename(path)}"
        )

        return True

    def _close_tab(
        self,
        index,
        confirm=True,
    ):
        if index < 0 or index >= self.tabs.count():
            return True

        tab = self.tabs.widget(index)

        if tab is None:
            return True

        modified = False

        if hasattr(tab, "is_modified"):
            modified = bool(tab.is_modified())
        else:
            modified = bool(
                getattr(tab, "modified", False)
            )

        if modified and confirm:
            file_label = (
                os.path.basename(tab.path)
                if getattr(tab, "path", None)
                else self._t("ui.untitled", "senza titolo")
            )
            result = QMessageBox.question(
                self,
                self._t(
                    "dialog.unsaved_title",
                    "Modifiche non salvate",
                ),
                self._t(
                    "dialog.unsaved_text",
                    "Il file '{file}' contiene modifiche non salvate.\n"
                    "Salvare prima di chiudere?",
                ).replace("{file}", file_label),
                (
                    QMessageBox.StandardButton.Save
                    | QMessageBox.StandardButton.Discard
                    | QMessageBox.StandardButton.Cancel
                ),
                QMessageBox.StandardButton.Save,
            )

            if result == QMessageBox.StandardButton.Cancel:
                return False

            if result == QMessageBox.StandardButton.Save:
                try:
                    saved = tab.save()
                except Exception as error:
                    QMessageBox.critical(
                        self,
                        "Errore di salvataggio",
                        f"Impossibile salvare il file.\n\n{error}",
                    )
                    return False

                if not saved:
                    return False

        self.tabs.removeTab(index)
        tab.deleteLater()

        return True

    def _close_project(self):
        open_count = self.tabs.count()

        if open_count > 0 or self.project_root:
            result = QMessageBox.question(
                self,
                self._t(
                    "dialog.close_project_title",
                    "Chiudi progetto",
                ),
                self._t(
                    "dialog.close_project_text",
                    "Chiudere il progetto?\n"
                    "Le {count} scheda/e aperta/e verrà/verranno chiuse.",
                ).replace("{count}", str(open_count)),
                (
                    QMessageBox.StandardButton.Yes
                    | QMessageBox.StandardButton.No
                ),
                QMessageBox.StandardButton.No,
            )

            if result != QMessageBox.StandardButton.Yes:
                return False

        if self.tabs.count() == 0:
            self.project.clear()
            self.project_root = ""
            self.settings.set(
                "project_dir",
                "",
            )
            self.status_msg.setText(
                self._t(
                    "status.no_project",
                    "Nessun progetto aperto",
                )
            )
            self.setWindowTitle(
                "QGIS Python IDE Pro"
            )
            return True

        while self.tabs.count() > 0:
            index = self.tabs.count() - 1

            if not self._close_tab(
                index,
                confirm=True,
            ):
                return False

        self.project.clear()

        # Elimina dalla memoria il percorso del progetto: dopo la
        # chiusura "Ricarica file del progetto" non deve piu'
        # trovare nulla da ricaricare.
        self.project_root = ""
        self.settings.set(
            "project_dir",
            "",
        )

        self.status_msg.setText(
            self._t(
                "status.no_project",
                "Nessun progetto aperto",
            )
        )

        self.setWindowTitle(
            "QGIS Python IDE Pro"
        )

        return True

    def _refresh_title(self):

        tab = self.current()

        title = "QGIS Python IDE Pro"

        if tab:

            title = (
                os.path.basename(tab.path)
                if tab.path
                else "nuovo.py"
            )

            if tab.modified:
                title += " *"

        self.setWindowTitle(
            f"{title} — QGIS Python IDE Pro"
        )

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    def _check(self):

        tab = self.current()

        if not tab:
            return

        self.diag.clear()

        diagnostics = self.analyzer.analyze(
            tab.text(),
            tab.path or "<editor>",
        )

        for diagnostic in diagnostics:

            item = QTreeWidgetItem(
                [
                    str(diagnostic.line),
                    str(diagnostic.column + 1),
                    diagnostic.severity,
                    diagnostic.message,
                    diagnostic.code,
                ]
            )

            item.setData(
                0,
                Qt.ItemDataRole.UserRole,
                diagnostic,
            )

            self.diag.addTopLevelItem(
                item
            )

        self.status_msg.setText(
            self._t("ui.diagnostics_count", "{count} diagnostiche").format(count=len(diagnostics))
        )

        self.progress.show()
        self._finish_progress(f"{len(diagnostics)} diagnostiche")

        # Mostra la scheda Diagnostica con i risultati.
        self.diag_dock.show()
        self.diag_dock.raise_()

    def _diag_context_menu(self, position):
        """Menu contestuale della scheda Diagnostica."""
        item = self.diag.itemAt(position)

        if item is not None:
            self.diag.setCurrentItem(item)

        menu = QMenu(self)

        quick_fix = menu.addAction(
            self.icon("quickfix"),
            self._t("action.quickFix", "Correzione rapida"),
        )
        quick_fix.triggered.connect(self._quick_fix)

        if item is not None:
            goto = menu.addAction(
                self._t("diag.goto_line", "Vai alla riga"),
            )
            goto.triggered.connect(
                lambda: self._goto_diag(item, 0)
            )

            diagnostic = item.data(
                0,
                Qt.ItemDataRole.UserRole,
            )
            copy_item = menu.addAction(
                self._t("quickfix.copy", "Copia diagnostica"),
            )
            copy_item.triggered.connect(
                lambda: QApplication.clipboard().setText(
                    diagnostic.message
                    if diagnostic
                    else item.text(0)
                )
            )

        menu.addSeparator()

        recheck = menu.addAction(
            self._t("diag.recheck", "Ricontrolla file corrente"),
        )
        recheck.triggered.connect(self._check)

        if self.diag.topLevelItemCount():
            clear_item = menu.addAction(
                self._t("diag.clear", "Cancella elenco"),
            )
            clear_item.triggered.connect(self.diag.clear)

        menu.exec(
            self.diag.viewport().mapToGlobal(position)
        )

    def _goto_diag(self, item, column):

        diagnostic = item.data(
            0,
            Qt.ItemDataRole.UserRole,
        )

        tab = self.current()

        if diagnostic and tab:
            tab.goto_line(
                diagnostic.line,
                diagnostic.column,
            )

    def _quick_fix(self):

        item = self.diag.currentItem()

        if not item:
            return

        diagnostic = item.data(
            0,
            Qt.ItemDataRole.UserRole,
        )

        tab = self.current()

        if not diagnostic or not tab:
            return

        menu = QMenu(self)
        menu.setMinimumWidth(340)

        # Azioni specifiche della regola rilevata.
        self._add_quick_fix_actions(
            menu,
            diagnostic,
        )

        # Azioni di suppressione secondo lo scanner di origine
        # (https://plugins.qgis.org/docs/security-scanning/skipping
        # e /config-files): bandit usa '# nosec', flake8 '# noqa',
        # detect-secrets '# pragma: allowlist secret'.
        self._add_suppression_actions(
            menu,
            diagnostic,
        )

        if not menu.isEmpty():
            menu.addSeparator()

        menu.addAction(
            self._t("quickfix.copy", "Copia diagnostica"),
            lambda: QApplication.clipboard().setText(
                diagnostic.message
            ),
        )

        if diagnostic.fix:
            menu.addAction(
                self._t("quickfix.copy_suggestion", "Copia suggerimento"),
                lambda: QApplication.clipboard().setText(
                    diagnostic.fix
                ),
            )

        menu.addAction(
            self._t("quickfix.ignore", "Ignora")
        )

        menu.exec(
            self.diag.viewport().mapToGlobal(
                self.diag.visualItemRect(
                    item
                ).topLeft()
            )
        )

    # ------------------------------------------------------------------
    # Quick fix helpers
    # ------------------------------------------------------------------

    def _get_line(self, line):

        tab = self.current()

        if not tab:
            return None, ""

        lines = tab.text().splitlines(
            True
        )

        if 1 <= line <= len(lines):
            return lines, lines[line - 1]

        return lines, ""

    def _replace_line_text(self, line, new_text):

        tab = self.current()

        if not tab:
            return

        lines = tab.text().splitlines(
            True
        )

        if 1 <= line <= len(lines):
            ending = "\n" if lines[line - 1].endswith("\n") else ""
            lines[line - 1] = new_text.rstrip("\n") + ending
            tab.replace_document_text(
                "".join(lines)
            )

        self._check()

    def _transform_line(self, line, transform):

        lines, text = self._get_line(line)

        if not text:
            return

        new_text = transform(text)

        if new_text and new_text != text:
            self._replace_line_text(
                line,
                new_text,
            )

    def _ensure_import(self, module_name):

        tab = self.current()

        if not tab:
            return

        text = tab.text()

        if re.search(
            r"^\s*(import|from)\s+" + re.escape(module_name) + r"(\s|\.)",
            text,
            re.MULTILINE,
        ):
            return

        lines = text.splitlines(
            True
        )

        insert_at = 0

        for index, content in enumerate(lines):
            if re.match(
                r"^\s*(import|from)\s+\S+",
                content,
            ):
                insert_at = index + 1

        lines.insert(
            insert_at,
            f"import {module_name}\n",
        )

        tab.replace_document_text(
            "".join(lines)
        )

    def _add_quick_fix_actions(self, menu, diagnostic):

        line = diagnostic.line
        code = diagnostic.code

        def action(label, callback):
            menu.addAction(
                self.icon("quickfix"),
                label,
                callback,
            )

        if code == "QGIS001":

            action(
                self._t("quickfix.generate", "Inserisci codice / Genera implementazione"),
                lambda: self._insert_at(
                    diagnostic.line,
                    "    raise NotImplementedError(\"Implementazione richiesta\")\n",
                ),
            )

            action(
                self._t("quickfix.remove_pass", "Elimina pass"),
                lambda: self._delete_line(
                    diagnostic.line
                ),
            )

        elif code == "F401":

            action(
                "Rimuovi import",
                lambda: self._delete_line(
                    diagnostic.line
                ),
            )

        elif code == "QGIS010":

            action(
                "Aggiungi controllo layer=None",
                lambda: self._insert_after(
                    diagnostic.line,
                    "if layer is None:\n"
                    "    return\n",
                ),
            )

        elif code == "S101":
            # assert cond, msg  ->  if not (cond): raise AssertionError(msg)

            def fix_assert():

                lines, text = self._get_line(line)

                if not text:
                    return

                match = re.match(
                    r"^(\s*)assert\s+(.+?)(?:,\s*(.+?))?\s*$",
                    text.rstrip("\n"),
                )

                if not match:
                    return

                indent = match.group(1)
                condition = match.group(2)
                message = match.group(3)

                if message:
                    replacement = (
                        f"{indent}if not ({condition}):\n"
                        f"{indent}    raise AssertionError({message})\n"
                    )
                else:
                    replacement = (
                        f"{indent}if not ({condition}):\n"
                        f"{indent}    raise AssertionError()\n"
                    )

                self._replace_line_text(
                    line,
                    replacement,
                )

            action(
                "Sostituisci con raise AssertionError",
                fix_assert,
            )

        elif code == "S307":

            def fix_eval():
                self._transform_line(
                    line,
                    lambda text: re.sub(
                        r"\beval\(",
                        "ast.literal_eval(",
                        text,
                        count=1,
                    ),
                )
                self._ensure_import("ast")

            action(
                "Sostituisci con ast.literal_eval(...)",
                fix_eval,
            )

        elif code == "S306":

            action(
                "Sostituisci con tempfile.mkstemp()",
                lambda: self._transform_line(
                    line,
                    lambda text: text.replace(
                        "mktemp(",
                        "mkstemp(",
                    ),
                ),
            )

        elif code == "S324":

            action(
                "Sostituisci con hashlib.sha256()",
                lambda: self._transform_line(
                    line,
                    lambda text: text.replace(
                        "md5", "sha256"
                    ).replace(
                        "sha1", "sha256"
                    ),
                ),
            )

        elif code == "S506":

            def fix_yaml():
                def transform(text):
                    if "safe_load" in text:
                        return text
                    return text.replace(
                        "yaml.load(",
                        "yaml.safe_load(",
                    )

                self._transform_line(
                    line,
                    transform,
                )

            action(
                "Sostituisci con yaml.safe_load(...)",
                fix_yaml,
            )

        elif code == "S602":

            def fix_shell():
                def transform(text):
                    new = text.replace(
                        "shell=True", "shell=False"
                    )
                    new = new.replace(
                        "shell = True", "shell = False"
                    )
                    return new

                self._transform_line(
                    line,
                    transform,
                )

            action(
                "Imposta shell=False",
                fix_shell,
            )

        elif code == "S310":

            def fix_timeout():
                def transform(text):
                    stripped = text.rstrip("\n")
                    ending = "\n" if text.endswith("\n") else ""
                    if stripped.endswith(")"):
                        return (
                            stripped[:-1]
                            + ", timeout=30)"
                            + ending
                        )
                    return text

                self._transform_line(
                    line,
                    transform,
                )

            action(
                "Aggiungi timeout=30",
                fix_timeout,
            )

        elif code == "S105":

            def fix_secret():
                lines, text = self._get_line(line)

                if not text:
                    return

                match = re.match(
                    r"^(\s*)([A-Za-z_]\w*)\s*=",
                    text,
                )

                if not match:
                    return

                indent = match.group(1)
                variable = match.group(2)

                replacement = (
                    f"{indent}{variable} = os.environ.get("
                    f'"{variable.upper()}", ""'
                    f")  # TODO: configura la variabile d'ambiente\n"
                )

                self._replace_line_text(
                    line,
                    replacement,
                )
                self._ensure_import("os")

            action(
                "Sposta in variabile d'ambiente (os.environ)",
                fix_secret,
            )

        elif code == "S110":

            action(
                "Sostituisci pass con raise",
                lambda: self._transform_line(
                    line,
                    lambda text: re.sub(
                        r"^(\s*)pass\s*$",
                        r"\1raise",
                        text.rstrip("\n"),
                    ) + ("\n" if text.endswith("\n") else ""),
                ),
            )

        elif code in ("E711", "E712"):

            def fix_comparison():
                def transform(text):
                    replacements = [
                        ("== None", "is None"),
                        ("!= None", "is not None"),
                        ("== True", "is True"),
                        ("== False", "is False"),
                        ("!= True", "is not True"),
                        ("!= False", "is not False"),
                    ]
                    for old, new in replacements:
                        text = text.replace(old, new)
                    return text

                self._transform_line(
                    line,
                    transform,
                )

            action(
                "Sostituisci con is / is not",
                fix_comparison,
            )

        elif code == "F841":

            def fix_unused():
                lines, text = self._get_line(line)

                if not text:
                    return

                new = re.sub(
                    r"^(\s*)([A-Za-z]\w*)(\s*=)",
                    r"\1_\2\3",
                    text,
                    count=1,
                )

                if new != text:
                    self._replace_line_text(
                        line,
                        new,
                    )

            action(
                "Rinomina con prefisso '_'",
                fix_unused,
            )

    def _add_suppression_actions(self, menu, diagnostic):

        line = diagnostic.line
        code = diagnostic.code

        def add_comment(comment):

            lines, text = self._get_line(line)

            if not text:
                return

            stripped = text.rstrip("\n")
            ending = "\n" if text.endswith("\n") else ""

            self._replace_line_text(
                line,
                f"{stripped}  {comment}{ending}",
            )

        # Bandit: https://plugins.qgis.org/docs/security-scanning —
        # salta con '# nosec' opzionalmente qualificato '# nosec: B###'.
        if code.startswith("S") and code not in ("S105",):
            bandit_id = code[1:]
            menu.addAction(
                self._t(
                    "quickfix.nosec",
                    "Aggiungi '# nosec: {code}' (Bandit)",
                ).replace("{code}", code),
                lambda: add_comment(f"# nosec: {bandit_id}"),
            )

        # detect-secrets: '# pragma: allowlist secret'.
        if code == "S105":
            menu.addAction(
                self._t(
                    "quickfix.allowlist",
                    "Aggiungi '# pragma: allowlist secret' (detect-secrets)",
                ),
                lambda: add_comment("# pragma: allowlist secret"),
            )

        # Flake8: '# noqa' oppure '# noqa: CODE'.
        if code.startswith(("F", "E", "W")):
            menu.addAction(
                self._t(
                    "quickfix.noqa",
                    "Aggiungi '# noqa: {code}' (Flake8)",
                ).replace("{code}", code),
                lambda: add_comment(f"# noqa: {code}"),
            )

    def _delete_line(self, line):

        tab = self.current()

        if not tab:
            return

        lines = tab.text().splitlines(
            True
        )

        if 1 <= line <= len(lines):
            del lines[line - 1]
            tab.replace_document_text(
                "".join(lines)
            )

        self._check()

    def _insert_at(self, line, text):

        tab = self.current()

        if not tab:
            return

        lines = tab.text().splitlines(
            True
        )

        lines.insert(
            max(0, line),
            text,
        )

        tab.replace_document_text(
            "".join(lines)
        )

        self._check()

    def _insert_after(self, line, text):
        self._insert_at(
            line,
            text,
        )

    # ------------------------------------------------------------------
    # Formatting
    # ------------------------------------------------------------------

    def _format(self):
        tab = self.current()
        if not tab:
            return

        suffix = (
            os.path.splitext(tab.path or "")[1]
            or self._tab_suffix(tab)
        ).lower()

        # reformatCode() di QScintilla e' un no-op senza formatter
        # registrato: usa sempre il motore interno, che conserva
        # cursore, selezione e scroll tramite replace_document_text.
        formatted = format_document(tab.text(), suffix)
        if formatted != tab.text():
            tab.replace_document_text(formatted)
            self._refresh_title()

    def _trim(self):

        tab = self.current()

        if tab:
            tab.replace_document_text(
                trim_trailing(
                    tab.text()
                )
            )

            self._refresh_title()

    def _comment(self):
        tab = self.current()
        if tab and hasattr(tab, "comment"):
            tab.comment()

    def _uncomment(self):
        tab = self.current()
        if tab and hasattr(tab, "uncomment"):
            tab.uncomment()


    def _complete_line(self):

        tab = self.current()

        if (
            tab
            and hasattr(
                tab.editor,
                "setFocus",
            )
        ):
            tab.editor.setFocus()
            self._show_completion(
                tab.editor
            )

    # ------------------------------------------------------------------
    # Completion / Documentation
    # ------------------------------------------------------------------

    def _show_completion(self, editor):

        tab = self.current()

        if not tab:
            return

        line, column = (
            tab.cursor_location()
        )

        items = complete_editor(
            self.language,
            tab.text(),
            line + 1,
            column,
            self._tab_suffix(tab),
        )

        if not items:
            return

        def insert(symbol):

            editor_widget = tab.editor

            if hasattr(
                editor_widget,
                "getCursorPosition",
            ):

                current_line, current_column = (
                    editor_widget.getCursorPosition()
                )

                start = current_column

                lines = tab.text().splitlines()

                text = (
                    lines[current_line]
                    if current_line < len(lines)
                    else ""
                )

                match = re.search(
                    r"[A-Za-z_]\w*$",
                    text[:current_column],
                )

                start = (
                    match.start()
                    if match
                    else current_column
                )

                editor_widget.setSelection(
                    current_line,
                    start,
                    current_line,
                    current_column,
                )

                editor_widget.replaceSelectedText(
                    symbol.name
                )

            else:
                editor_widget.insertPlainText(
                    symbol.name
                )

        popup = CompletionPopup(
            editor,
            items,
            insert,
        )

        position = editor.mapToGlobal(
            editor.rect().bottomLeft()
        )

        popup.move(position)
        popup.show()
        popup.setFocus()

    def _show_documentation(self, editor):

        tab = self.current()

        if not tab:
            return

        expression = tab.word_under_cursor()

        symbol = self.language.documentation(
            expression,
            tab.text(),
        )

        if symbol:

            self.api_doc.setHtml(
                f"<h2>{symbol.name}</h2>"
                f"<p><b>{symbol.type_name}</b></p>"
                f"<pre>{symbol.signature}</pre>"
                f"<p>{symbol.doc}</p>"
            )

            self.api_dock.show()
            self.api_dock.raise_()

    def _toggle_console(self):
        visible = self.console_dock.isVisible()
        self.console_dock.setVisible(not visible)
        if not visible:
            self.console.input.setFocus()

    def _reload_qgis_runtime(self):
        if self.api_indexer.worker is not None:
            self.status_msg.setText(self._t("status.indexing_busy", "Indicizzazione già in corso"))
            return
        self.progress.show()
        self.progress.setRange(0, 0)
        self.status_msg.setText(self._t("status.reloading_api", "Ricaricamento librerie e API QGIS…"))
        started, signals = self.api_indexer.start(True)
        if started:
            signals.finished.connect(self._api_index_finished)
            signals.failed.connect(self._api_index_failed)

    def _self_check(self):
        checker = PluginSelfChecker(os.path.dirname(os.path.dirname(__file__)))
        self.progress.show()
        self.progress.setRange(0, 0)
        self.status_msg.setText(self._t("status.self_check", "Verifica integrità plugin…"))
        results = checker.run()
        failed = [r for r in results if not r.ok]
        for result in results:
            self.log.append(
                f"{result.name}: {result.detail}" if result.detail else result.name,
                "ERROR" if not result.ok else "INFO",
            )
        self.progress.setRange(0, 100)
        self.progress.setValue(0 if failed else 100)
        self.status_msg.setText(
            self._t("status.self_check_failed", "Verifica: {count} controlli falliti").format(count=len(failed))
            if failed else
            self._t("status.self_check_ok", "Verifica completata: {count} controlli OK").format(count=len(results))
        )

    def _tabs_context_menu(self, position):
        """Menu contestuale delle schede."""
        index = self.tabs.tabBar().tabAt(position)

        if index < 0:
            return

        self.tabs.setCurrentIndex(index)

        menu = QMenu(self)

        close_action = menu.addAction(
            self.icon("close"),
            self._t("tab.close", "Chiudi scheda"),
        )
        close_action.triggered.connect(
            lambda: self._close_tab(index)
        )

        close_others_action = menu.addAction(
            self.icon("close-others"),
            self._t(
                "tab.close_others",
                "Chiudi tutte tranne questa",
            ),
        )
        close_others_action.triggered.connect(
            lambda: self._close_other_tabs(index)
        )

        close_all_action = menu.addAction(
            self.icon("close-all"),
            self._t("tab.close_all", "Chiudi tutto"),
        )
        close_all_action.triggered.connect(
            lambda: self._close_all_tabs()
        )

        menu.exec(
            self.tabs.tabBar().mapToGlobal(position)
        )

    def _close_other_tabs(self, keep_index):
        """Chiude tutte le schede tranne quella indicata.

        Interrompe la chiusura se l'utente annulla il salvataggio
        di una scheda con modifiche non salvate.
        """
        for index in range(self.tabs.count() - 1, -1, -1):
            if index == keep_index:
                continue

            if not self._close_tab(index):
                break

    def _close_all_tabs(self):
        """Chiude tutte le schede, comprese quella attiva.

        Interrompe la chiusura se l'utente annulla il salvataggio
        di una scheda con modifiche non salvate.
        """
        for index in range(self.tabs.count() - 1, -1, -1):
            if not self._close_tab(index):
                break

    # ------------------------------------------------------------------
    # API
    # ------------------------------------------------------------------

    def _refresh_api(self):
        self._reload_qgis_runtime()

    def _populate_api(self):

        self.api_list.clear()

        for symbol in sorted(
            self.language.symbols.values(),
            key=lambda value: value.name.lower(),
        ):

            item = QListWidgetItem(
                self.icon("docs"),
                f"{symbol.name}    "
                f"{symbol.type_name or symbol.kind}",
            )

            item.setData(
                Qt.ItemDataRole.UserRole,
                symbol,
            )

            self.api_list.addItem(
                item
            )

    def _filter_api(self, text):

        query = text.lower()

        for index in range(
            self.api_list.count()
        ):

            item = self.api_list.item(
                index
            )

            item.setHidden(
                bool(
                    query
                    and query not in item.text().lower()
                )
            )

    def _show_api_item(self, item):

        symbol = item.data(
            Qt.ItemDataRole.UserRole
        )

        if not symbol:
            return

        self.api_doc.setHtml(
            f"<h2>{symbol.name}</h2>"
            f"<p><b>{symbol.kind}</b> — "
            f"{symbol.type_name}</p>"
            f"<pre>{symbol.signature}</pre>"
            f"<p>{symbol.doc}</p>"
        )

    # ------------------------------------------------------------------
    # Runner
    # ------------------------------------------------------------------

    def _run(self):

        tab = self.current()

        if not tab:
            return

        self.progress.show()
        self.progress.setRange(0, 0)

        self.status_msg.setText(
            "Esecuzione in QGIS…"
        )

        self.log.append(
            f"Avvio: {tab.path or '<editor>'}",
            "INFO",
        )

        self.runner.run_in_qgis(
            tab.text(),
            tab.path or "<editor>",
        )

    def _run_external(self):

        tab = self.current()

        if tab:

            self.progress.show()
            self.progress.setRange(0, 0)

            self.runner.run_external(
                tab.text(),
                tab.path or "<editor>",
            )

    def _run_selection(self):

        tab = self.current()

        if (
            tab
            and tab.selected_text()
        ):
            self.runner.run_in_qgis(
                tab.selected_text(),
                tab.path or "<selection>",
            )

    def _run_block(self):

        tab = self.current()

        if not tab:
            return

        lines = tab.text().splitlines()

        line, _ = (
            tab.cursor_location()
        )

        start = line
        end = line

        while (
            start > 0
            and lines[start - 1].strip()
        ):
            start -= 1

        while (
            end + 1 < len(lines)
            and lines[end + 1].strip()
        ):
            end += 1

        self.runner.run_in_qgis(
            "\n".join(
                lines[start:end + 1]
            ),
            tab.path or "<block>",
        )

    def _stop(self):
        self.runner.stop()

    def _runner_output(self, message, level):
        self.log.append(
            self.i18n.tr(str(message), str(message)),
            level,
        )

    def _runner_finished(self, ok):

        self._finish_progress(
            self._t("status.process_ok", "Completato")
            if ok
            else self._t("status.process_error", "Errore")
        )

        self.status_msg.setText(
            "Processo completato"
            if ok
            else "Processo terminato con errori"
        )

    # ------------------------------------------------------------------
    # Qt Designer
    # ------------------------------------------------------------------

    def _designer(self):

        tab = self.current()
        path = tab.path if tab else None

        if (
            path
            and path.lower().endswith(".ui")
        ):
            open_designer(path)
        else:
            open_designer(None)

    def _compile_ui(self):

        tab = self.current()

        if (
            tab
            and tab.path
            and tab.path.lower().endswith(".ui")
        ):
            compile_ui(tab.path)

        else:

            QMessageBox.information(
                self,
                "UI → Python",
                "Apri prima un file .ui.",
            )

    def _load_ui_widget(self, path):
        """Carica un file .ui e restituisce il widget top-level.

        Prova nell'ordine:
        1. QtUiTools.QUiLoader (nativo, veloce);
        2. uic.loadUi di PyQt (puro Python: disponibile anche nelle
           installazioni QGIS prive del modulo QtUiTools, tipico su Windows);
        3. fallback: finestra di sola lettura con il contenuto XML del .ui.
        """
        try:
            from qgis.PyQt.QtCore import QFile
            from qgis.PyQt.QtUiTools import QUiLoader

            ui_file = QFile(path)

            if not ui_file.open(QFile.OpenModeFlag.ReadOnly):
                raise RuntimeError(
                    f"Impossibile aprire il file UI:\n{path}"
                )

            try:
                widget = QUiLoader().load(ui_file, self)
            finally:
                ui_file.close()

            if widget is not None:
                return widget
            raise RuntimeError(
                "QUiLoader non ha restituito un widget valido."
            )
        except ImportError:
            pass

        try:
            from qgis.PyQt import uic

            widget = uic.loadUi(path)

            if widget is not None:
                return widget
            raise RuntimeError(
                "uic.loadUi non ha restituito un widget valido."
            )
        except ImportError:
            pass

        # Fallback finale: mostra il sorgente XML del file .ui in una
        # finestra di sola lettura, cosi' l'anteprima non fallisce mai.
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as handle:
                content = handle.read()
        except OSError as error:
            raise RuntimeError(
                f"Nessun loader UI disponibile e lettura file fallita: {error}"
            )

        dialog = QDialog(self)
        dialog.setWindowTitle(
            f"Anteprima XML — {os.path.basename(path)}"
        )
        dialog.resize(640, 480)

        layout = QVBoxLayout(dialog)

        info = QLabel(
            "QtUiTools e uic non sono disponibili in questa "
            "installazione QGIS: viene mostrato il sorgente XML "
            "del file .ui.",
            dialog,
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        view = QTextBrowser(dialog)
        view.setPlainText(content)
        try:
            from qgis.PyQt.QtGui import QFontDatabase

            view.setFont(
                QFontDatabase.systemFont(
                    QFontDatabase.SystemFont.FixedFont
                )
            )
        except Exception:  # nosec B110 -- guardia difensiva UI
            pass
        layout.addWidget(view)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Close,
            parent=dialog,
        )
        buttons.rejected.connect(dialog.reject)
        buttons.accepted.connect(dialog.accept)
        layout.addWidget(buttons)

        dialog.setAttribute(
            Qt.WidgetAttribute.WA_DeleteOnClose,
            True,
        )

        return dialog

    def _preview_ui(self) -> None:
        tab = self.current()

        if not tab or not tab.path:
            QMessageBox.information(
                self,
                "Anteprima UI",
                "Apri prima un file .ui.",
            )
            return

        if not tab.path.lower().endswith(".ui"):
            QMessageBox.information(
                self,
                "Anteprima UI",
                "L'anteprima è disponibile solo per i file .ui.",
            )
            return

        try:
            widget = self._load_ui_widget(tab.path)

            widget.setAttribute(
                Qt.WidgetAttribute.WA_DeleteOnClose,
                True,
            )

            widget.setWindowTitle(
                f"Anteprima — {os.path.basename(tab.path)}"
            )

            widget.show()
            widget.raise_()
            widget.activateWindow()

            if not hasattr(self, "_ui_previews"):
                self._ui_previews = []

            self._ui_previews.append(widget)

            widget.destroyed.connect(
                lambda _=None, obj=widget:
                    self._remove_ui_preview(obj)
            )

            self.log.append(
                f"Anteprima UI aperta: {tab.path}",
                "INFO",
            )

        except Exception as error:
            QMessageBox.critical(
                self,
                "Anteprima UI",
                f"Impossibile visualizzare l'anteprima.\n\n{error}",
            )

            self.log.append(
                f"Anteprima UI fallita: {error}",
                "ERROR",
            )


    def _remove_ui_preview(self, widget) -> None:
        previews = getattr(
            self,
            "_ui_previews",
            [],
        )

        if widget in previews:
            previews.remove(widget)

    # ------------------------------------------------------------------
    # Snippets
    # ------------------------------------------------------------------

    def _snippet_menu(self):

        menu = QMenu(self)
        menu.setMinimumWidth(320)

        for name, text in (
            self.snippets.all().items()
        ):

            # Il nome dello snippet viene tradotto secondo la lingua
            # corrente (chiave "snippet.<nome>" nei file di traduzione);
            # il nome originale e' il fallback.
            display_name = self._t(
                f"snippet.{name}",
                name,
            )

            menu.addAction(
                display_name,
                lambda value=text:
                    self._insert_text(value),
            )

        menu.exec(
            self.cursor().pos()
        )

    def _insert_text(self, text):

        tab = self.current()

        if not tab:
            return

        if hasattr(
            tab.editor,
            "insertPlainText",
        ):
            tab.editor.insertPlainText(
                text
            )

        elif hasattr(
            tab.editor,
            "replaceSelectedText",
        ):
            tab.editor.replaceSelectedText(
                text
            )

    # ------------------------------------------------------------------
    # Plugin wizard
    # ------------------------------------------------------------------

    def _wizard_form_dialog(self):
        """Dialogo con i campi del wizard: restituisce i dati o None."""
        dialog = QDialog(self)
        dialog.setWindowTitle(
            self._t("wizard.title", "Wizard plugin QGIS 4")
        )
        dialog.setMinimumWidth(420)

        layout = QVBoxLayout(dialog)

        form = QFormLayout()
        form.setSpacing(6)

        name_edit = QLineEdit(dialog)
        desc_edit = QLineEdit(dialog)
        author_edit = QLineEdit(dialog)
        email_edit = QLineEdit(dialog)
        version_edit = QLineEdit(dialog)
        menu_edit = QLineEdit(dialog)

        desc_edit.setText("Un plugin QGIS 4")
        version_edit.setText("1.0.0")

        form.addRow(
            self._t("wizard.plugin_name", "Nome plugin:"), name_edit
        )
        form.addRow(
            self._t("wizard.description", "Descrizione:"), desc_edit
        )
        form.addRow(
            self._t("wizard.author", "Autore:"), author_edit
        )
        form.addRow(
            self._t("wizard.email", "Email:"), email_edit
        )
        form.addRow(
            self._t("wizard.version", "Versione:"), version_edit
        )
        form.addRow(
            self._t("wizard.menu", "Voce di menu:"), menu_edit
        )

        extras_check = QCheckBox(
            self._t(
                "wizard.extras",
                "Includi README.md, .gitignore e icon.svg",
            ),
            dialog,
        )
        extras_check.setChecked(True)
        layout.addLayout(form)
        layout.addWidget(extras_check)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel,
            parent=dialog,
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        if not dialog.exec():
            return None

        name = name_edit.text().strip()
        if not name:
            QMessageBox.warning(
                self,
                self._t("wizard.title", "Wizard plugin"),
                self._t(
                    "wizard.name_required",
                    "Il nome del plugin è obbligatorio.",
                ),
            )
            return None

        menu_name = menu_edit.text().strip() or name
        return {
            "name": name,
            "description": desc_edit.text().strip(),
            "author": author_edit.text().strip(),
            "email": email_edit.text().strip(),
            "version": version_edit.text().strip() or "1.0.0",
            "menu": menu_name,
            "extras": extras_check.isChecked(),
        }

    @staticmethod
    def _wizard_safe_module_name(name):
        """Converte il nome in un identificativo valido per Python."""
        safe = re.sub(r"[^0-9a-zA-Z_]+", "_", name.strip())
        safe = re.sub(r"_+", "_", safe).strip("_").lower()
        if not safe:
            safe = "plugin"
        if safe[0].isdigit():
            safe = "plugin_" + safe
        return safe

    @staticmethod
    def _wizard_class_name(module_name):
        """Converte il nome modulo in un nome di classe CamelCase."""
        return "".join(
            part.capitalize()
            for part in module_name.split("_")
            if part
        ) or "Plugin"

    def _plugin_wizard(self):
        """Genera uno scheletro completo di plugin QGIS 4 (Qt6-safe).

        Struttura secondo la documentazione ufficiale QGIS
        (https://docs.qgis.org/3.44/en/docs/user_manual/plugins/plugins.html)
        e le regole di migrazione QGIS 4
        (https://plugins.qgis.org/docs/migrate-qgis4):

        - metadata.txt completo con qgisMinimumVersion=4.0 e
          qgisMaximumVersion=4.99 (niente supportsQt6, rimosso da QGIS);
        - __init__.py con classFactory(iface);
        - modulo principale con QAction in menu e toolbar, i18n e
          Message Bar, usando soltanto qgis.PyQt (shim Qt5/Qt6);
        - icon.svg, README.md e .gitignore opzionali.
        """

        folder = QFileDialog.getExistingDirectory(
            self,
            self._t(
                "wizard.destination",
                "Cartella destinazione plugin QGIS 4",
            ),
        )

        if not folder:
            return

        data = self._wizard_form_dialog()

        if not data:
            return

        name = data["name"]
        module = self._wizard_safe_module_name(name)
        class_name = self._wizard_class_name(module)
        display_name = name.replace('"', "").replace("\n", " ")
        description = data["description"] or "Un plugin QGIS 4"
        author = data["author"] or "Generated by QGIS Python IDE Pro"
        email = data["email"]
        version = data["version"]
        menu_name = data["menu"].replace('"', "")

        root = os.path.join(
            folder,
            module,
        )

        os.makedirs(
            root,
            exist_ok=True,
        )

        os.makedirs(
            os.path.join(
                root,
                "icons",
            ),
            exist_ok=True,
        )

        # --------------------------------------------------------------
        # metadata.txt completo. qgisMaximumVersion=4.99 marca il
        # plugin come "QGIS 4 ready" (migrate-qgis4); NON aggiungere
        # supportsQt6: la flag e' stata rimossa da QGIS core.
        # --------------------------------------------------------------

        metadata_lines = [
            "[general]",
            f"name={display_name}",
            f"description={description}",
            f"about={description}",
            f"version={version}",
            "qgisMinimumVersion=4.0",
            "qgisMaximumVersion=4.99",
            f"author={author}",
        ]

        if email:
            metadata_lines.append(f"email={email}")

        metadata_lines.extend(
            [
                "changelog=Versione iniziale",
                "tags=python,qgis4",
                "homepage=",
                "repository=",
                "tracker=",
                "category=Plugins",
                "icon=icon.svg",
                "experimental=False",
                "deprecated=False",
                "hasProcessingProvider=no",
            ]
        )

        Path(
            os.path.join(
                root,
                "metadata.txt",
            )
        ).write_text(
            "\n".join(metadata_lines) + "\n",
            encoding="utf-8",
        )

        # --------------------------------------------------------------
        # __init__.py — punto di ingresso richiesto da QGIS.
        # --------------------------------------------------------------

        init_code = (
            "def classFactory(iface):\n"
            "    \"\"\"Load the plugin class.\n\n"
            "    :param iface: A QGIS interface instance.\n"
            "    :type iface: QgsInterface\n"
            "    \"\"\"\n"
            f"    from .{module} import {class_name}\n"
            f"    return {class_name}(iface)\n"
        )

        Path(
            os.path.join(
                root,
                "__init__.py",
            )
        ).write_text(
            init_code,
            encoding="utf-8",
        )

        # --------------------------------------------------------------
        # Modulo principale — Qt6-safe: solo import qgis.PyQt
        # (shim Qt5/Qt6), QAction da QtGui, enum qualified, i18n con
        # QCoreApplication.translate e Message Bar di Qgis.
        # --------------------------------------------------------------

        plugin_code = (
            "import os\n"
            "import inspect\n\n"
            "from qgis.PyQt.QtCore import QCoreApplication\n"
            "from qgis.PyQt.QtGui import QIcon, QAction\n\n"
            "from qgis.core import Qgis\n"
            "from qgis.utils import iface\n\n\n"
            f"class {class_name}:\n"
            "    \"\"\"QGIS 4 Plugin.\"\"\"\n\n"
            "    def __init__(self, iface):\n"
            "        self.iface = iface\n"
            "        self.plugin_dir = os.path.dirname(\n"
            "            inspect.getfile(inspect.currentframe())\n"
            "        )\n"
            "        self.actions = []\n"
            f"        self.menu = self.tr(\"&{menu_name}\")\n"
            f"        self.toolbar_name = \"{display_name}\"\n"
            "        self.toolbar = None\n\n"
            "    def tr(self, message):\n"
            "        \"\"\"Translate using Qt translation API.\"\"\"\n"
            "        return QCoreApplication.translate(\n"
            f"            \"{class_name}\", message\n"
            "        )\n\n"
            "    def add_action(\n"
            "        self,\n"
            "        icon_path,\n"
            "        text,\n"
            "        callback,\n"
            "        enabled_flag=True,\n"
            "        add_to_menu=True,\n"
            "        add_to_toolbar=True,\n"
            "        status_tip=None,\n"
            "        whats_this=None,\n"
            "        parent=None,\n"
            "    ):\n"
            "        \"\"\"Add an action to menu and toolbar.\"\"\"\n"
            "        icon = QIcon(icon_path)\n"
            "        action = QAction(\n"
            "            icon, text, parent or self.iface.mainWindow()\n"
            "        )\n"
            "        action.triggered.connect(callback)\n"
            "        action.setEnabled(enabled_flag)\n\n"
            "        if status_tip is not None:\n"
            "            action.setStatusTip(status_tip)\n\n"
            "        if whats_this is not None:\n"
            "            action.setWhatsThis(whats_this)\n\n"
            "        if add_to_toolbar:\n"
            "            self.toolbar = self.iface.addToolBar(\n"
            "                self.toolbar_name\n"
            "            )\n"
            f"            self.toolbar.setObjectName(\"{module}_toolbar\")\n"
            "            self.toolbar.addAction(action)\n\n"
            "        if add_to_menu:\n"
            "            self.iface.addPluginToMenu(self.menu, action)\n\n"
            "        self.actions.append(action)\n"
            "        return action\n\n"
            "    def initGui(self):\n"
            "        \"\"\"Create menu entries and toolbar icons.\"\"\"\n"
            "        icon_path = os.path.join(\n"
            "            self.plugin_dir, \"icons\", \"plugin.svg\"\n"
            "        )\n"
            "        self.add_action(\n"
            "            icon_path,\n"
            f"            text=self.tr(\"{display_name}\"),\n"
            "            callback=self.run,\n"
            "            parent=self.iface.mainWindow(),\n"
            "        )\n\n"
            "    def unload(self):\n"
            "        \"\"\"Remove the plugin menu item and toolbar icons.\"\"\"\n"
            "        for action in self.actions:\n"
            "            self.iface.removePluginMenu(self.menu, action)\n"
            "            self.iface.removeToolBarIcon(action)\n\n"
            "        if self.toolbar is not None:\n"
            "            del self.toolbar\n\n"
            "        self.actions = []\n\n"
            "    def run(self):\n"
            "        \"\"\"Run method that performs all the real work.\"\"\"\n"
            "        level = (\n"
            "            Qgis.MessageLevel.Info\n"
            "            if hasattr(Qgis, \"MessageLevel\")\n"
            "            else Qgis.Info\n"
            "        )\n"
            "        self.iface.messageBar().pushMessage(\n"
            f"            self.tr(\"{display_name}\"),\n"
            "            self.tr(\"Plugin caricato correttamente.\"),\n"
            "            level=level,\n"
            "            duration=3,\n"
            "        )\n"
        )

        Path(
            os.path.join(
                root,
                f"{module}.py",
            )
        ).write_text(
            plugin_code,
            encoding="utf-8",
        )

        # --------------------------------------------------------------
        # Extra: icona SVG, README e .gitignore.
        # --------------------------------------------------------------

        if data["extras"]:
            svg = (
                "<svg xmlns=\"http://www.w3.org/2000/svg\" "
                "width=\"24\" height=\"24\" viewBox=\"0 0 24 24\">"
                "<rect width=\"24\" height=\"24\" rx=\"4\" "
                "fill=\"#589632\"/>"
                "<text x=\"12\" y=\"17\" font-size=\"13\" "
                "text-anchor=\"middle\" fill=\"#ffffff\">"
                + module[:2].upper()
                + "</text></svg>\n"
            )

            Path(
                os.path.join(
                    root,
                    "icons",
                    "plugin.svg",
                )
            ).write_text(
                svg,
                encoding="utf-8",
            )

            readme = (
                f"# {display_name}\n\n"
                f"{description}\n\n"
                "## Installazione\n\n"
                "Copiare la cartella del plugin nella directory dei "
                "plugin di QGIS oppure creare un archivio ZIP della "
                "cartella e installarlo da *Plugin → Gestisci ed "
                "installa plugin → Installa da ZIP*.\n\n"
                "## Compatibilità\n\n"
                "- QGIS >= 4.0 (Qt 6)\n"
                "- `qgisMaximumVersion=4.99` in `metadata.txt` "
                "(vedi https://plugins.qgis.org/docs/migrate-qgis4)\n"
            )

            Path(
                os.path.join(
                    root,
                    "README.md",
                )
            ).write_text(
                readme,
                encoding="utf-8",
            )

            Path(
                os.path.join(
                    root,
                    ".gitignore",
                )
            ).write_text(
                "__pycache__/\n*.pyc\n*.pyo\n.idea/\n.vscode/\n"
                "*.zip\n*.bak\n",
                encoding="utf-8",
            )

        self._populate_project(
            root
        )

        self._open_path(
            os.path.join(
                root,
                f"{module}.py",
            )
        )

        self.log.append(
            f"Wizard QGIS 4: plugin '{display_name}' creato in {root}",
            "INFO",
        )

    # ------------------------------------------------------------------
    # Command palette
    # ------------------------------------------------------------------

    def _command_palette(self):

        dialog = QDialog(self)

        dialog.setWindowTitle(
            self._t("palette.title", "Command Palette")
        )

        dialog.resize(
            650,
            480,
        )

        layout = QVBoxLayout(
            dialog
        )

        edit = QLineEdit()

        edit.setPlaceholderText(
            self._t("palette.placeholder", "Digita un comando…")
        )

        layout.addWidget(
            edit
        )

        list_widget = QListWidget()

        layout.addWidget(
            list_widget,
            1,
        )

        def refill():

            list_widget.clear()

            for command in self.commands.search(
                edit.text()
            ):

                item = QListWidgetItem(
                    self.icon("palette"),
                    f"{command.category}  ›  "
                    f"{command.title}",
                )

                item.setData(
                    Qt.ItemDataRole.UserRole,
                    command,
                )

                list_widget.addItem(
                    item
                )

        edit.textChanged.connect(
            refill
        )

        def activate(item):

            command = item.data(
                Qt.ItemDataRole.UserRole
            )

            if command:
                action = command.action
                trigger = getattr(action, "trigger", None)
                if callable(trigger):
                    trigger()
                elif callable(action):
                    action()
                else:
                    raise TypeError(
                        f"L'azione del comando '{command.id}' non è eseguibile."
                    )

            dialog.accept()

        list_widget.itemActivated.connect(
            activate
        )

        refill()

        dialog.exec()

    # ------------------------------------------------------------------
    # Find / Replace
    # ------------------------------------------------------------------

    def _show_find_replace(self) -> None:
        """Mostra il pannello Trova/Sostituisci."""
        self.find_replace_dock.show()
        self.find_replace_dock.raise_()
        self.find_replace.focus_search()


    def _find_replace_pattern(
        self,
        query: str,
        payload: dict[str, object],
    ):
        """Costruisce il pattern di ricerca secondo le opzioni del pannello."""
        if not query:
            return None

        pattern_text = query

        if not bool(payload.get("regex", False)):
            pattern_text = re.escape(pattern_text)

        if bool(payload.get("whole_word", False)):
            pattern_text = rf"\b{pattern_text}\b"

        flags = 0

        if not bool(payload.get("case_sensitive", False)):
            flags |= re.IGNORECASE

        try:
            return re.compile(
                pattern_text,
                flags,
            )
        except re.error:
            return None


    def _find_replace_navigate(
        self,
        query,
        forward,
        payload,
    ):
        """Trova l'occorrenza precedente o successiva nei documenti aperti."""
        pattern = self._find_replace_pattern(
            query,
            payload,
        )

        if pattern is None:
            self.find_replace._set_result(0)
            return

        documents = self._open_documents()

        if not documents:
            self.find_replace._set_result(0)
            return

        current = self._current_document()

        if current is None or current not in documents:
            current = documents[0]

        current_index = documents.index(current)

        ordered_documents = []

        if forward:
            ordered_documents.extend(
                documents[current_index:]
            )
            ordered_documents.extend(
                documents[:current_index]
            )
        else:
            ordered_documents.extend(
                reversed(
                    documents[:current_index + 1]
                )
            )
            ordered_documents.extend(
                reversed(
                    documents[current_index + 1:]
                )
            )

        for document in ordered_documents:
            text = document.text()

            if not text:
                continue

            offset = document.cursor_offset()

            if forward:
                match = pattern.search(
                    text,
                    offset,
                )

                if match is None and offset > 0:
                    match = pattern.search(
                        text,
                        0,
                    )
            else:
                # "Precedente": se la selezione corrente e' gia' una
                # corrispondenza, partire PRIMA di essa altrimenti il
                # pulsante riseleziona sempre la stessa occorrenza.
                limit = offset

                selection_offsets = (
                    document.selection_offsets()
                )

                if selection_offsets is not None:
                    selected = document.selected_text()

                    if selected and pattern.fullmatch(
                        selected
                    ):
                        limit = selection_offsets[0]

                matches = list(
                    pattern.finditer(
                        text,
                        0,
                        limit,
                    )
                )

                if matches:
                    match = matches[-1]
                else:
                    matches = list(
                        pattern.finditer(text)
                    )

                    match = (
                        matches[-1]
                        if matches
                        else None
                    )

            if match is None:
                continue

            self.tabs.setCurrentWidget(
                document
            )

            document.select_text_range(
                match.start(),
                match.end(),
            )

            return

        self.find_replace._set_result(0)


    def _find_replace_replace(
        self,
        query,
        replacement,
        payload,
    ):
        """Sostituisce l'occorrenza corrente o la prima successiva."""
        pattern = self._find_replace_pattern(
            query,
            payload,
        )

        if pattern is None:
            self.find_replace._set_result(0)
            return

        document = self._current_document()

        if document is None:
            return

        selected = document.selected_text()

        if selected:
            selected_match = pattern.fullmatch(
                selected
            )

            if selected_match is not None:
                selection = document.selection_offsets()

                if selection is not None:
                    start, end = selection

                    if bool(payload.get("regex", False)):
                        value = selected_match.expand(
                            replacement
                        )
                    else:
                        value = replacement

                    document.replace_text_range(
                        start,
                        end,
                        value,
                    )

                    self.find_replace._update_count()
                    return

        self._find_replace_navigate(
            query,
            True,
            payload,
        )

        document = self._current_document()

        if document is None:
            return

        selected = document.selected_text()

        if not selected:
            return

        selected_match = pattern.fullmatch(
            selected
        )

        if selected_match is None:
            return

        selection = document.selection_offsets()

        if selection is None:
            return

        start, end = selection

        if bool(payload.get("regex", False)):
            value = selected_match.expand(
                replacement
            )
        else:
            value = replacement

        document.replace_text_range(
            start,
            end,
            value,
        )

        self.find_replace._update_count()


    def _find_replace_replace_all(
        self,
        query,
        replacement,
        payload,
    ):
        """Sostituisce tutte le occorrenze nel documento o nei documenti aperti."""
        pattern = self._find_replace_pattern(
            query,
            payload,
        )

        if pattern is None:
            self.find_replace._set_result(0)
            return

        documents = self.find_replace._documents()

        total = 0

        for document in documents:
            text = document.text()

            matches = list(
                pattern.finditer(text)
            )

            if not matches:
                continue

            for match in reversed(matches):
                if bool(payload.get("regex", False)):
                    value = match.expand(
                        replacement
                    )
                else:
                    value = replacement

                document.replace_text_range(
                    match.start(),
                    match.end(),
                    value,
                )

                total += 1

        self.find_replace._set_result(
            total
        )


    def _find_replace_document_changed(
        self,
        _index: int,
    ) -> None:
        """Aggiorna il conteggio quando cambia documento."""
        if hasattr(self, "find_replace"):
            self.find_replace._update_count()

    # ------------------------------------------------------------------
    # Undo / Redo
    # ------------------------------------------------------------------

    def _undo(self):

        tab = self.current()

        if tab:
            tab.editor.undo()

    def _redo(self):

        tab = self.current()

        if tab:
            tab.editor.redo()

    # ------------------------------------------------------------------
    # Project search
    # ------------------------------------------------------------------

    def _project_search(self):
        self.log_dock.show()
        self.log_dock.raise_()
        self.log.show()
        self.log.raise_()

        root = str(
            getattr(self, "project_root", "") or ""
        ).strip() or str(
            self.settings.get("project_dir", "") or ""
        ).strip()

        query = (
            self.global_search.text()
            .strip()
        )

        if not root or not query:
            return

        hits = []

        for directory_path, directories, files in os.walk(root):

            directories[:] = [
                directory
                for directory in directories
                if directory not in {
                    ".git",
                    ".venv",
                    "__pycache__",
                    "venv",
                }
            ]

            for filename in files:

                extension = os.path.splitext(
                    filename
                )[1].lower()

                if extension not in EditorTab.SUPPORTED:
                    continue

                path = os.path.join(
                    directory_path,
                    filename,
                )

                try:

                    with open(
                        path,
                        encoding="utf-8",
                    ) as file:

                        for line_number, line in enumerate(
                            file,
                            1,
                        ):

                            if query.lower() in line.lower():

                                hits.append(
                                    f"{filename}:"
                                    f"{line_number}: "
                                    f"{line.strip()}"
                                )

                except (
                    OSError,
                    UnicodeDecodeError,
                ):
                    continue

        self.log.append(
            f'Ricerca progetto "{query}": '
            f"{len(hits)} risultati",
            "INFO",
        )

        if hits:
            self.log.append(
                "\n".join(hits[:200]),
                "INFO",
            )

    def _project_search_status(self):
        return None

    # ------------------------------------------------------------------
    # URL
    # ------------------------------------------------------------------

    def _open_url(self, url):
        QDesktopServices.openUrl(
            QUrl(url)
        )
