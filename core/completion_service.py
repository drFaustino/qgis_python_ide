"""Servizio di completamento professionale e multilinguaggio.

Integra:
- Python: language service PyQGIS (simboli live caricati a runtime, API
  incluse) + parole del documento come fallback intelligente;
- XML / Qt Designer .ui: tag, attributi e chiusura automatica dei tag
  aperti (suggerisce il tag da chiudere con '</');
- QSS / CSS: proprieta', valori comuni, pseudo-stati e sub-control;
- JSON: chiavi e valori (true/false/null + chiavi gia' usate nel doc);
- TypeScript/JavaScript: keyword, globali e parole del documento.

Tutti i suggerimenti sono "ignorabili": il popup si chiude con Esc e non
inserisce nulla finche' non si conferma.
"""

from __future__ import annotations

import re
from collections import Counter

try:
    from .language_service import Symbol
except ImportError:  # pragma: no cover - esecuzione standalone
    from language_service import Symbol  # type: ignore


MAX_ITEMS = 200

# ----------------------------------------------------------------------
# Cataloghi
# ----------------------------------------------------------------------

UI_TAGS = (
    "widget", "property", "attribute", "item", "spacer", "layout",
    "action", "addaction", "signal", "slot", "connection",
    "QWidget", "QDialog", "QMainWindow", "QLabel", "QPushButton",
    "QToolButton", "QLineEdit", "QTextEdit", "QPlainTextEdit",
    "QComboBox", "QCheckBox", "QRadioButton", "QSpinBox",
    "QDoubleSpinBox", "QSlider", "QTabWidget", "QTableWidget",
    "QTableView", "QTreeWidget", "QTreeView", "QListWidget",
    "QListView", "QGroupBox", "QScrollArea", "QSplitter",
    "QStackedWidget", "QProgressBar", "QDateEdit", "QTimeEdit",
    "QDateTimeEdit", "QMenuBar", "QToolBar", "QStatusBar",
    "QVBoxLayout", "QHBoxLayout", "QGridLayout", "QFormLayout",
    "QFrame", "QgsMapCanvas", "QgsFieldComboBox",
    "QgsProjectionSelectionWidget", "QgsFileWidget", "QgsColorButton",
    "QgsSpinBox", "QgsDoubleSpinBox", "QgsFilterLineEdit",
    "QgsCollapsibleGroupBox", "QgsExtentGroupBox", "QgsScaleWidget",
)

XML_ATTRS = (
    "class", "name", "objectName", "geometry", "windowTitle",
    "toolTip", "styleSheet", "font", "enabled", "visible", "checked",
    "text", "title", "icon", "shortcut", "minimum", "maximum", "value",
    "size", "policy", "alignment", "row", "column", "rowspan",
    "colspan", "stretch", "buddy", "value", "stdset", "native",
)

CSS_PROPERTIES = (
    "color", "background", "background-color", "border", "border-top",
    "border-bottom", "border-left", "border-right", "border-style",
    "border-width", "border-color", "border-radius", "border-image",
    "padding", "padding-top", "padding-bottom", "padding-left",
    "padding-right", "margin", "margin-top", "margin-bottom",
    "margin-left", "margin-right", "font", "font-family", "font-size",
    "font-style", "font-weight", "min-width", "min-height", "max-width",
    "max-height", "width", "height", "spacing", "outline",
    "outline-color", "outline-style", "outline-radius",
    "selection-color", "selection-background-color",
    "selection-border-color", "alternate-background-color",
    "icon-size", "image", "image-position", "position", "left", "top",
    "right", "bottom", "gridline-color", "qproperty-icon",
    "qproperty-iconSize", "qproperty-size", "qproperty-text",
)

CSS_VALUES = (
    "none", "solid", "dashed", "dotted", "double", "groove", "ridge",
    "inset", "outset", "transparent", "inherit", "auto", "bold",
    "italic", "normal", "underline", "overline", "line-through",
    "center", "left", "right", "top", "bottom", "repeat", "no-repeat",
    "fixed", "absolute", "relative", "block", "inline", "inline-block",
)

QSS_SUBCONTROLS = (
    "::add-line", "::sub-line", "::up-arrow", "::down-arrow",
    "::left-arrow", "::right-arrow", "::handle", "::groove",
    "::indicator", "::menu-indicator", "::menu-arrow", "::item",
    "::branch", "::title", "::close-button", "::float-button",
    "::section", "::corner", "::tab", "::tab-bar", "::tear",
)

QSS_PSEUDO_STATES = (
    ":hover", ":pressed", ":checked", ":unchecked", ":disabled",
    ":enabled", ":focus", ":indeterminate", ":selected", ":on",
    ":off", ":active", ":default", ":flat", ":open", ":closable",
    ":movable", ":first", ":last", ":middle", ":only-one",
)

CSS_KEYWORDS = tuple(dict.fromkeys(CSS_PROPERTIES + CSS_VALUES))

JSON_KEYS = (
    "name", "version", "description", "author", "email", "homepage",
    "repository", "tracker", "tags", "category", "icon", "changelog",
    "experimental", "deprecated", "license", "keywords", "main",
    "scripts", "dependencies", "devDependencies", "peerDependencies",
    "qgisMinimumVersion", "qgisMaximumVersion", "hasProcessingProvider",
)

TS_KEYWORDS = (
    "const", "let", "var", "function", "interface", "type", "class",
    "import", "from", "export", "default", "return", "async", "await",
    "keyof", "extends", "implements", "readonly", "private", "public",
    "protected", "string", "number", "boolean", "void", "never",
    "any", "unknown", "null", "undefined", "true", "false", "new",
    "this", "super", "of", "in", "if", "else", "for", "while",
    "switch", "case", "break", "continue", "try", "catch", "finally",
    "throw", "do", "typeof", "instanceof", "yield", "enum",
    "namespace", "declare", "abstract", "static", "get", "set",
    "constructor", "satisfies", "as", "asserts", "infer",
)

TS_GLOBALS = (
    "console", "window", "document", "globalThis", "JSON", "Math",
    "Promise", "Array", "Object", "String", "Number", "Boolean",
    "Date", "Map", "Set", "WeakMap", "WeakSet", "Error", "TypeError",
    "RangeError", "fetch", "setTimeout", "clearTimeout",
    "setInterval", "clearInterval", "requestAnimationFrame",
    "localStorage", "sessionStorage", "URL", "URLSearchParams",
    "Intl", "Reflect", "Proxy", "Symbol", "BigInt", "RegExp",
)

WORD_RE = re.compile(r"[A-Za-z_]\w{2,}")


def _symbols_from_catalog(
    names,
    prefix,
    kind,
    suffix="",
):
    """Costruisce Symbol dal catalogo filtrando per prefisso."""
    return [
        Symbol(
            name=name + suffix,
            kind=kind,
        )
        for name in names
        if name.lower().startswith(prefix.lower())
    ][:MAX_ITEMS]


def _document_words(source, limit=60):
    """Parole piu' frequenti del documento (classi, funzioni, chiavi)."""
    counts = Counter(
        WORD_RE.findall(source)
    )
    return [
        word
        for word, _ in counts.most_common(limit)
    ]


def _word_symbols(
    source,
    prefix,
    exclude=(),
):
    """Suggerimenti dalle parole gia' presenti nel documento."""
    excluded = set(exclude)
    seen = set()
    result = []

    for word in _document_words(source):
        if not word.lower().startswith(prefix.lower()):
            continue
        if word in seen or word in excluded:
            continue
        seen.add(word)
        result.append(
            Symbol(
                name=word,
                kind="word",
            )
        )

    return result[:MAX_ITEMS]


def _merge(*groups):
    """Unisce gruppi di Symbol eliminando i duplicati per nome."""
    seen = set()
    merged = []

    for group in groups:
        for symbol in group:
            if symbol.name in seen:
                continue
            seen.add(symbol.name)
            merged.append(symbol)

    return merged[:MAX_ITEMS]


def _context_line(source, line, column):
    lines = source.splitlines()
    if 0 < line <= len(lines):
        current = lines[line - 1]
    else:
        current = ""
    column = max(0, min(column, len(current)))
    return current[:column]


def _up_to_cursor(source, line, column):
    """Testo completo dalla prima riga fino al cursore (multiriga)."""
    lines = source.splitlines()
    if 0 < line <= len(lines):
        lines = lines[:line]
        lines[-1] = lines[-1][:column]
    return "\n".join(lines)


# ----------------------------------------------------------------------
# Completamento per linguaggio
# ----------------------------------------------------------------------

def _complete_xml(source, line, column):
    before = _context_line(source, line, column)

    context = _up_to_cursor(source, line, column)
    before = _context_line(source, line, column)

    # Valore attributo dentro virgolette: nessun suggerimento strutturale.
    if re.search(r"[\w.-]+=[\"'][^\"']*$", context):
        return []

    # Chiusura tag: '</' -> suggerisce i tag aperti non ancora chiusi.
    closing = re.search(r"</([A-Za-z_]\w*)?$", context)
    if closing:
        prefix = closing.group(1) or ""
        stack = []
        for match in re.finditer(
            r"<(/?)([A-Za-z_][\w.-]*)([^>]*)>",
            context,
        ):
            closing_slash, tag, rest = match.groups()
            self_closed = rest.rstrip().endswith("/")
            if closing_slash:
                if stack and stack[-1] == tag:
                    stack.pop()
            elif not self_closed:
                stack.append(tag)
        candidates = list(
            dict.fromkeys(
                tag
                for tag in reversed(stack)
                if tag.startswith(prefix)
            )
        )
        if candidates:
            return [
                Symbol(name=tag, kind="tag")
                for tag in candidates[:MAX_ITEMS]
            ]
        return _symbols_from_catalog(UI_TAGS, prefix, "tag")

    # Apertura tag: '<' o '<prefisso'.
    opening = re.search(r"<([A-Za-z_]\w*)?$", context)
    if opening:
        prefix = opening.group(1) or ""
        return _symbols_from_catalog(UI_TAGS, prefix, "tag")

    # Attributi dentro un tag: '<tag attr...' senza '>' prima.
    inside_tag = re.search(
        r"<[A-Za-z_][\w.-]*[^>]*?\s([\w.-]*)$", context
    )
    if inside_tag:
        prefix = inside_tag.group(1) or ""
        return _symbols_from_catalog(
            XML_ATTRS, prefix, "attribute"
        )

    prefix_match = re.search(r"[A-Za-z_]\w*$", before)
    prefix = prefix_match.group(0) if prefix_match else ""
    return _word_symbols(source, prefix)


def _complete_css(source, line, column):
    context = _up_to_cursor(source, line, column)
    before = _context_line(source, line, column)

    # Sub-control e pseudo-stati dopo il selettore (fuori dai blocchi).
    sub = re.search(r"::?([\w-]*)$", context)
    if sub and "{" not in context.rsplit(";", 1)[-1]:
        prefix = sub.group(1) or ""

        def _match(name):
            stripped = name.lstrip(":")
            return not prefix or stripped.startswith(prefix)

        return _merge(
            [
                Symbol(name=name, kind="sub-control")
                for name in QSS_SUBCONTROLS
                if _match(name)
            ],
            [
                Symbol(name=name, kind="pseudo-state")
                for name in QSS_PSEUDO_STATES
                if _match(name)
            ],
        )[:MAX_ITEMS]

    segment = context.rsplit("{", 1)[-1]

    # Valore dopo ':' (senza ';' successivo nel blocco corrente).
    if ":" in segment and ";" not in segment:
        prefix_match = re.search(r"[A-Za-z-][\w-]*$", before)
        prefix = prefix_match.group(0) if prefix_match else ""
        return _merge(
            _symbols_from_catalog(CSS_VALUES, prefix, "value"),
            _word_symbols(source, prefix, exclude=CSS_KEYWORDS),
        )

    # Proprieta' all'interno di un blocco (dopo '{' o ';').
    if "{" in context:
        prefix_match = re.search(r"-?[\w-]*$", before)
        prefix = prefix_match.group(0) if prefix_match else ""
        return _merge(
            _symbols_from_catalog(
                CSS_PROPERTIES, prefix, "property"
            ),
            _word_symbols(source, prefix, exclude=CSS_KEYWORDS),
        )

    # Selettore: parole del documento.
    prefix_match = re.search(r"[A-Za-z_][\w-]*$", before)
    prefix = prefix_match.group(0) if prefix_match else ""
    return _word_symbols(source, prefix, exclude=CSS_KEYWORDS)


def _complete_json(source, line, column):
    context = _up_to_cursor(source, line, column)

    # Valore dopo i due punti.
    if re.search(r":\s*[\"']?[\w\"']*$", context):
        prefix_match = re.search(r"[A-Za-z_]\w*$", context)
        prefix = prefix_match.group(0) if prefix_match else ""
        constants = [
            Symbol(name="true", kind="value"),
            Symbol(name="false", kind="value"),
            Symbol(name="null", kind="value"),
        ]
        if prefix:
            constants = [
                symbol
                for symbol in constants
                if symbol.name.startswith(prefix)
            ]
        values = re.findall(r":\s*\"([^\"]+)\"", source)
        value_symbols = [
            Symbol(name=value, kind="value")
            for value in dict.fromkeys(values)
            if value.lower().startswith(prefix.lower())
        ][:MAX_ITEMS]
        return _merge(constants, value_symbols)

    # Chiave: dopo '{' o ',' con possibile apertura virgolette.
    key_match = re.search(r"[\"']([\w.-]*)$", context)
    if key_match and re.search(r"[{,]\s*[\"']?[\w.-]*$", context):
        prefix = key_match.group(1) or ""
        used = re.findall(r"[\"']([\w.-]+)[\"']\s*:", source)
        return _merge(
            [
                Symbol(name=name, kind="key")
                for name in dict.fromkeys(used)
                if name.lower().startswith(prefix.lower())
            ],
            _symbols_from_catalog(JSON_KEYS, prefix, "key"),
        )

    return []


def _complete_ts(source, line, column):
    before = _context_line(source, line, column)
    prefix_match = re.search(r"[A-Za-z_$][\w$]*$", before)
    prefix = prefix_match.group(0) if prefix_match else ""

    return _merge(
        _symbols_from_catalog(TS_KEYWORDS, prefix, "keyword"),
        _symbols_from_catalog(TS_GLOBALS, prefix, "global"),
        _word_symbols(source, prefix, exclude=TS_KEYWORDS + TS_GLOBALS),
    )


# ----------------------------------------------------------------------
# Entry point
# ----------------------------------------------------------------------

def complete_editor(
    language_service,
    source,
    line,
    column,
    suffix,
):
    """Restituisce i suggerimenti per l'editor corrente.

    :param language_service: PyQGISLanguageService condiviso (Python).
    :param suffix: estensione del file corrente (es. '.ui', '.qss').
    """
    suffix = (suffix or "").lower()

    if suffix in (".py", ".pyw"):
        items = language_service.completions(
            source, line, column
        )
        if len(items) < 10:
            before = _context_line(source, line, column)
            match = re.search(r"[A-Za-z_]\w*$", before)
            prefix = match.group(0) if match else ""
            items = _merge(
                items,
                _word_symbols(source, prefix),
            )
        return items

    if suffix in (".xml", ".ui", ".svg"):
        return _complete_xml(source, line, column)

    if suffix in (".css", ".qss", ".scss"):
        return _complete_css(source, line, column)

    if suffix == ".json":
        return _complete_json(source, line, column)

    if suffix in (".ts", ".js", ".jsx", ".tsx", ".mjs"):
        return _complete_ts(source, line, column)

    # Fallback generico: parole del documento.
    before = _context_line(source, line, column)
    match = re.search(r"[A-Za-z_]\w*$", before)
    prefix = match.group(0) if match else ""
    return _word_symbols(source, prefix)
