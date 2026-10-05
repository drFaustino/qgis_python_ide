"""Toolbar contestuale per file XML e QSS/CSS.

Fornisce le azioni realmente utili per questi linguaggi (niente
grassetto/corsivo, che non esistono in XML/CSS):

- XML: commenta/decommenta (<!-- -->), racchiudi in tag, chiudi tag
  aperto, formattazione/indentazione del documento;
- QSS/CSS: commenta/decommenta (/* */), inserimento pseudo-stati e
  sub-control QSS, inserimento colore, snippet di proprieta' comuni.
"""

from __future__ import annotations

import re

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QHBoxLayout,
    QInputDialog,
    QMenu,
    QMessageBox,
    QToolButton,
    QWidget,
)

QSS_PSEUDO_STATES = (
    ":hover", ":pressed", ":checked", ":unchecked", ":disabled",
    ":enabled", ":focus", ":indeterminate", ":selected", ":on",
    ":off", ":active", ":default", ":flat", ":open", ":closable",
    ":movable", ":first", ":last", ":middle", ":only-one",
)

QSS_SUBCONTROLS = (
    "::add-line", "::sub-line", "::up-arrow", "::down-arrow",
    "::left-arrow", "::right-arrow", "::handle", "::groove",
    "::indicator", "::menu-indicator", "::menu-arrow", "::item",
    "::branch", "::title", "::close-button", "::float-button",
    "::section", "::corner", "::tab", "::tab-bar", "::tear",
)

CSS_PROPERTY_SNIPPETS = (
    ("border", "border: 1px solid #999999;"),
    ("border-radius", "border-radius: 4px;"),
    ("padding", "padding: 4px;"),
    ("margin", "margin: 4px;"),
    ("background-color", "background-color: #ffffff;"),
    ("color", "color: #222222;"),
    ("font", "font: bold 10pt;"),
    ("selection-background-color", "selection-background-color: #589632;"),
)

STYLE_SHEET = """
    QToolButton {
        min-width: 24px;
        max-width: 30px;
        min-height: 22px;
        max-height: 22px;
        padding: 2px;
        margin: 0px;
        border: 1px solid transparent;
        border-radius: 3px;
        background: transparent;
        font-size: 11px;
    }

    QToolButton:hover {
        background: rgba(127, 127, 127, 45);
        border: 1px solid rgba(127, 127, 127, 110);
    }

    QToolButton:pressed {
        background: rgba(127, 127, 127, 80);
        border: 1px solid rgba(127, 127, 127, 140);
    }

    #styleToolbarSeparator {
        background: rgba(127, 127, 127, 80);
        margin: 3px 2px;
    }
"""


class StyleToolbar(QWidget):
    """Toolbar per XML (flavor='xml') o QSS/CSS (flavor='style')."""

    def __init__(self, editor, flavor, parent=None):
        super().__init__(parent)
        self.editor = editor
        self.flavor = flavor

        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(2)

        self.setStyleSheet(STYLE_SHEET)

        if flavor == "xml":
            self._build_xml(layout)
        else:
            self._build_style(layout)

        layout.addStretch(1)

    # ------------------------------------------------------------------
    # Costruzione
    # ------------------------------------------------------------------

    def _build_xml(self, layout):
        self._add_button(
            layout,
            "💬",
            "Commenta/Decommenta righe (<!-- -->)",
            self._toggle_comment_xml,
        )
        self._add_button(
            layout,
            "🏷",
            "Racchiudi la selezione in un tag…",
            self._wrap_in_tag,
        )
        self._add_button(
            layout,
            "❯/",
            "Chiudi il tag aperto alla posizione del cursore",
            self._close_open_tag,
        )
        self._add_separator(layout)
        self._add_button(
            layout,
            "≡",
            "Formatta e indenta il documento XML",
            self._format_xml,
        )

    def _build_style(self, layout):
        self._add_button(
            layout,
            "💬",
            "Commenta/Decommenta righe (/* */)",
            self._toggle_comment_style,
        )
        self._add_separator(layout)
        self._add_menu_button(
            layout,
            ":h ▾",
            "Inserisci pseudo-stato QSS (:hover, :checked…)",
            [(name, name) for name in QSS_PSEUDO_STATES],
        )
        self._add_menu_button(
            layout,
            ":: ▾",
            "Inserisci sub-control QSS (::handle, ::groove…)",
            [(name, name) for name in QSS_SUBCONTROLS],
        )
        self._add_separator(layout)
        self._add_button(
            layout,
            "🎨",
            "Inserisci colore…",
            self._insert_color,
        )
        self._add_menu_button(
            layout,
            "▤ ▾",
            "Inserisci proprieta' CSS comuni",
            list(CSS_PROPERTY_SNIPPETS),
        )

    # ------------------------------------------------------------------
    # Widget helpers
    # ------------------------------------------------------------------

    def _add_button(self, layout, text, tooltip, callback):
        button = QToolButton(self)
        button.setText(text)
        button.setToolTip(tooltip)
        button.setAutoRaise(True)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        button.clicked.connect(callback)
        layout.addWidget(button)
        return button

    def _add_menu_button(self, layout, text, tooltip, entries):
        button = self._add_button(
            layout,
            text,
            tooltip,
            lambda: None,
        )
        menu = QMenu(self)

        for label, value in entries:
            action = menu.addAction(label)
            action.triggered.connect(
                lambda checked=False, v=value: self._insert_text(v)
            )

        button.setMenu(menu)
        button.setPopupMode(
            QToolButton.ToolButtonPopupMode.InstantPopup
        )
        return button

    def _add_separator(self, layout):
        from qgis.PyQt.QtWidgets import QFrame

        line = QFrame(self)
        line.setObjectName("styleToolbarSeparator")
        line.setFrameShape(QFrame.Shape.VLine)
        line.setFixedWidth(1)
        line.setFixedHeight(16)
        layout.addWidget(line)
        return line

    # ------------------------------------------------------------------
    # Operazioni editor
    # ------------------------------------------------------------------

    def _replace_all(self, new_text, line_delta=0, column_delta=0):
        """Sostituisce tutto il documento preservando (approssimativamente)
        la posizione del cursore. Funziona su QUALSIASI QsciScintilla:
        replace_document_text appartiene a EditorTab, non all'editor."""
        editor = self.editor

        line, column = editor.getCursorPosition()
        old_lines = editor.text().split("\n")

        editor.selectAll()
        editor.replaceSelectedText(new_text)

        new_lines = new_text.split("\n")
        line = max(0, min(line + line_delta, len(new_lines) - 1))
        column = max(
            0,
            min(column + column_delta, len(new_lines[line])),
        )
        editor.setCursorPosition(line, column)

    def _target_lines(self):
        """(sl, el) delle righe selezionate o della riga del cursore."""
        if self.editor.hasSelectedText():
            sl, _sc, el, _ec = self.editor.getSelection()
            return sl, el
        sl, _sc = self.editor.getCursorPosition()
        return sl, sl

    def _insert_text(self, text):
        self.editor.insert(text)
        self.editor.setFocus()

    def _toggle_comment(self, opener, closer):
        """Toggle commento sulle righe selezionate (o riga corrente),
        preservando la posizione del cursore."""
        sl, el = self._target_lines()

        old_lines = self.editor.text().split("\n")

        if sl >= len(old_lines):
            return

        el = min(el, len(old_lines) - 1)

        new_lines = list(old_lines)
        cursor_delta = 0

        for i in range(sl, el + 1):
            line = old_lines[i]
            indent = line[:len(line) - len(line.lstrip())]
            content = line.strip()

            if content.startswith(opener) and content.endswith(closer):
                inner = content[len(opener):-len(closer)].strip()
                new_lines[i] = indent + inner
            else:
                new_lines[i] = (
                    indent + opener + " " + content + " " + closer
                )

            if i == sl:
                cursor_delta = len(new_lines[i]) - len(line)

        self._replace_all(
            "\n".join(new_lines),
            column_delta=cursor_delta if sl == el else 0,
        )
        self.editor.setFocus()

    def _toggle_comment_xml(self):
        self._toggle_comment("<!--", "-->")

    def _toggle_comment_style(self):
        self._toggle_comment("/*", "*/")

    def _wrap_in_tag(self):
        tag, ok = QInputDialog.getText(
            self,
            "Racchiudi in tag",
            "Nome del tag:",
        )

        tag = tag.strip()

        if not ok or not tag:
            return

        if self.editor.hasSelectedText():
            selected = self.editor.selectedText()
            self.editor.replaceSelectedText(
                f"<{tag}>{selected}</{tag}>"
            )
        else:
            line, col = self.editor.getCursorPosition()
            self.editor.insert(f"<{tag}></{tag}>")
            self.editor.setCursorPosition(line, col + len(tag) + 2)

        self.editor.setFocus()

    def _close_open_tag(self):
        line, col = self.editor.getCursorPosition()
        lines = self.editor.text().split("\n")

        # Considera tutta la riga corrente: il cursore puo' trovarsi
        # a meta' di un tag (<layout|>) e il '>' finale non deve
        # mancare dallo stack.
        up_to = "\n".join(
            lines[:line] + ([lines[line]] if line < len(lines) else [])
        )

        stack = []

        for match in re.finditer(
            r"<(/?)([A-Za-z_][\w.:-]*)((?:[^<>\"']|\"[^\"]*\"|'[^']*')*)>",
            up_to,
        ):
            closing, tag, rest = match.groups()
            self_closed = rest.rstrip().endswith("/")
            if closing:
                if stack and stack[-1] == tag:
                    stack.pop()
            elif not self_closed:
                stack.append(tag)

        if not stack:
            QMessageBox.information(
                self,
                "Chiudi tag",
                "Nessun tag aperto alla posizione del cursore.",
            )
            return

        self.editor.insert(f"</{stack[-1]}>")
        self.editor.setFocus()

    def _format_xml(self):
        try:
            try:
                from defusedxml import minidom
            except ImportError:
                # Fallback: defusedxml non e' installato in QGIS; il
                # documento proviene dai file aperti nell'IDE.
                from xml.dom import minidom  # nosec - fallback senza defusedxml

            old_text = self.editor.text()
            # Il documento e' il contenuto del file aperto nell'editor.
            dom = minidom.parseString(  # nosec - input dall'editor dell'IDE
                old_text
            )
            pretty = dom.toprettyxml(indent="  ")
            pretty = "\n".join(
                line for line in pretty.splitlines() if line.strip()
            )

            if not pretty.endswith("\n"):
                pretty += "\n"

        except Exception as error:
            QMessageBox.warning(
                self,
                "Formatta XML",
                f"Il documento non e' valido:\n{error}",
            )
            return

        old_line = self.editor.getCursorPosition()[0]
        old_count = max(1, len(old_text.split("\n")))
        new_count = max(1, len(pretty.split("\n")))

        self._replace_all(
            pretty,
            line_delta=int(old_line * new_count / old_count) - old_line,
        )
        self.editor.setFocus()

    def _insert_color(self):
        from qgis.PyQt.QtWidgets import QColorDialog

        color = QColorDialog.getColor(parent=self)

        if not color.isValid():
            return

        if color.alpha() == 255:
            value = color.name()
        else:
            value = (
                f"rgba({color.red()}, {color.green()}, "
                f"{color.blue()}, {color.alpha() / 255:.2f})"
            )

        self.editor.insert(value)
        self.editor.setFocus()
