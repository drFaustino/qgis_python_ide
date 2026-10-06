# QGIS Python IDE Pro

A professional, modular, responsive Python IDE for **QGIS 4 / Qt6**, inspired by the JetBrains experience. First public release: **1.0.0**. Current release: **1.1.0**.

## Requirements

- QGIS 4.x (Qt6 / PyQt6)
- No mandatory extra dependencies. Optional command-line tools are listed in `requirements-optional.txt` and are auto-detected at runtime.

## Installation

1. Extract the zip, or copy the `qgis_python_ide` folder into the active profile plugin directory:
   `~/.local/share/QGIS/QGIS4/profiles/default/python/plugins/`
2. Restart QGIS (or use *Plugin Reloader*).
3. Enable **QGIS Python IDE Pro** from *Plugins → Manage and Install Plugins…*.
4. Open the IDE from the toolbar or from the *Plugins → QGIS Python IDE Pro* menu.

## Main features

### Multi-format editor

- Multi-tab editor with state handling, view restore and multi-save
- **Python**, **Markdown**, **QSS**, **XML/UI**, **TXT** and configuration files
- Line numbers, code folding, syntax highlighting, completion and quick fixes
- Find & replace in file, dedicated Markdown and QSS toolbars

### PyQGIS language service

- Dynamic indexing of the running QGIS libraries (classes, methods, signals)
- Context-aware completion with type inference and method signatures
- Runtime API reload ("Reload libraries and QGIS APIs")

### Diagnostics and quick fixes

- Static AST analysis with error/warning codes (E711, E712, …)
- External linters integration: **ruff** (preferred) or **pyflakes** (fallback), auto-detected at runtime
- One-click **quick fixes** from the completion popup
- **Plugin integrity check** with a report in the log panel

### Integrated tools

- **Qt Designer**: edit `.ui` files and preview the window (pyuic6 / pyside6-uic / pyside6-designer)
- **Code wizard** and reusable **snippets**
- Built-in **Python console** and script execution with structured logging
- Live **Markdown preview**
- Formatting/beautify for **QSS**, **XML/UI** and **TXT**
- **Project-wide search** (grep over project files)
- **Command palette** for quick navigation
- **UI translations** (IT, EN, DE, ES, FR), switchable at runtime
- **Window layout** save/restore

## Extensions (sub-plugins)

Extension architecture in `extensions/<name>/extension.py` with a `create_extension()` factory and an optional module-level `register(window)`:

| Extension | Description |
|---|---|
| `local_history` | Automatic snapshots of saved files into `.ide_history/` (rotation: max 50 snapshots per file; excludes `.git`, `__pycache__`, `.ide_history`, `node_modules`, `.idea`). Manual snapshot action, restore with confirmation, open previous versions read-only |
| `todo_panel` | "Menu di controllo" dock: scans the project for TODO/FIXME/XXX/HACK comment markers, with translated column headers (Type / Position / Note). Refresh, Clear (with confirmation) and "Go to line" buttons; double-click or button jumps to the marker reusing the already open tab (no duplicates). The panel empties automatically when the project is closed; refresh warns when no project is open |
| `i18n_checker` | Cross-references translation keys used in code (`_t("…")`) against the project `*.json` catalogs; reports missing keys, per-language gaps and orphans. Shows a translated warning when no project is open |
| `session_manager` | Save, load and delete working sessions (sets of open tabs), persisted in `~/.qgis_ide_sessions.json` |
| `bookmarks` | Per-line bookmarks in open files; the manager dialog reopens the file and jumps to the line |

All extensions ship with dedicated SVG icons in the IDE icon theme.

## Extension translations

Every extension translates its messages into all IDE-supported languages (**it, en, de, es, fr**):

- Catalogs live in `extensions/<name>/translations/<language>.json`.
- If the JSON file is missing, the inline `MESSAGES` fallback is used.
- Classes inherit from `qgis_python_ide.core.ext_i18n.ExtensionBase` and translate with `self.tr("key")`.
- Extension modules are registered in `sys.modules` by the extension manager, so each extension can reliably locate its own folder and catalogs.
- The active language follows the IDE setting; if the extension is not attached to the window yet, the Qt system locale is used.
- Each module can expose `retranslate()`: it is called automatically when the IDE language changes, updating action texts, icons, dock titles, panel buttons and tree headers without a restart.
- At load time, if the catalog for the chosen language is missing, a warning is written to the IDE log so missing translations are always visible.

## Extension development

```python
from qgis_python_ide.core.ext_i18n import ExtensionBase

class MyExtension(ExtensionBase):
    name = "My Extension"
    actions = []

    def register(self, window):
        self._window = window
        # window: .iface, .tabs, .current(), .log, ._open_path(), .i18n, .run_script()

def create_extension():
    return MyExtension()
```

The **Extensions → Create extension (sub-plugin)…** wizard generates a ready skeleton; **Reload extensions** refreshes the Extensions menu without restarting QGIS. Optional module-level hooks: `register(window)` (called once after load) and `retranslate()` (called on every language change).

## Changelog

See `CHANGELOG.md` for the full release history.

## License

See `LICENSE`.
