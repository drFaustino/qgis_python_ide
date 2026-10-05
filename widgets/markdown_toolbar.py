from __future__ import annotations

from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import (
    QHBoxLayout,
    QToolButton,
    QWidget,
)


class MarkdownToolbar(QWidget):
    """
    Toolbar per la formattazione Markdown.

    La toolbar non conosce EditorTab:
    riceve semplicemente un editor Markdown compatibile
    con i metodi markdown_* definiti in MarkdownEditor.
    """

    previewRequested = pyqtSignal()

    def __init__(self, editor=None, parent=None):
        super().__init__(parent)
    
        self.editor = editor
        self._buttons = {}

        # La toolbar non deve mai diventare il proprietario del focus: in
        # particolare un click sui pulsanti non deve alterare la selezione
        # corrente dell'editor QScintilla.
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setObjectName("markdownToolbar")
        self.setAttribute(
            Qt.WidgetAttribute.WA_StyledBackground,
            True,
        )
    
        self.setMinimumHeight(24)
        self.setMaximumHeight(28)
        self.setContentsMargins(1, 1, 1, 1)
    
        self.setStyleSheet(
            """
            QToolBar {
                spacing: 1px;
                padding: 1px;
                margin: 0px;
                border: 0px;
                min-height: 24px;
                max-height: 28px;
            }
    
            QToolButton {
                min-width: 22px;
                max-width: 22px;
                min-height: 22px;
                max-height: 22px;
                padding: 2px;
                margin: 0px;
                border: 1px solid transparent;
                border-radius: 3px;
                background: transparent;
            }
    
            QToolButton:hover {
                background: rgba(127, 127, 127, 45);
                border: 1px solid rgba(127, 127, 127, 110);
            }
    
            QToolButton:pressed {
                background: rgba(127, 127, 127, 80);
                border: 1px solid rgba(127, 127, 127, 140);
            }

            #markdownToolbarSeparator {
                background: rgba(127, 127, 127, 80);
                margin: 3px 2px;
            }
            """
        )
    
        self._build_ui()

    def set_editor(self, editor):
        """Collega la toolbar a un editor Markdown."""
        self.editor = editor

    def _build_ui(self):
        layout = QHBoxLayout(self)

        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(2)

        self._add_character_buttons(layout)
        self._add_separator(layout)

        self._add_heading_buttons(layout)
        self._add_separator(layout)

        self._add_list_buttons(layout)
        self._add_separator(layout)

        self._add_quote_buttons(layout)
        self._add_separator(layout)

        self._add_insert_buttons(layout)
        self._add_separator(layout)

        self._add_preview_button(layout)

        layout.addStretch(1)

    def _add_character_buttons(self, layout):
        self._add_button(
            layout,
            "bold",
            "B",
            "Grassetto",
            self._bold,
        )

        self._add_button(
            layout,
            "italic",
            "I",
            "Corsivo",
            self._italic,
        )

        self._add_button(
            layout,
            "underline",
            "U",
            "Sottolineato",
            self._underline,
        )

        self._add_button(
            layout,
            "strikethrough",
            "S",
            "Barrato",
            self._strikethrough,
        )

        self._add_button(
            layout,
            "code",
            "<>",
            "Codice inline",
            self._inline_code,
        )

        self._add_button(
            layout,
            "superscript",
            "x²",
            "Apice",
            self._superscript,
        )

        self._add_button(
            layout,
            "subscript",
            "x₂",
            "Pedice",
            self._subscript,
        )

    def _add_heading_buttons(self, layout):
        for level in range(1, 7):
            self._add_button(
                layout,
                f"h{level}",
                f"H{level}",
                f"Titolo {level}",
                lambda checked=False, value=level:
                    self._heading(value),
            )

    def _add_list_buttons(self, layout):
        self._add_button(
            layout,
            "bullet",
            "•",
            "Elenco puntato",
            self._bullet_list,
        )

        self._add_button(
            layout,
            "numbered",
            "1.",
            "Elenco numerato",
            self._numbered_list,
        )

        self._add_button(
            layout,
            "checklist",
            "☑",
            "Checklist",
            self._checklist
        )

    def _add_quote_buttons(self, layout):
        self._add_button(
            layout,
            "quote",
            "“ ”",
            "Citazione",
            self._quote
        )

    def _add_insert_buttons(self, layout):
        self._add_button(
            layout,
            "link",
            "🔗",
            "Inserisci link",
            self._link
        )

        self._add_button(
            layout,
            "image",
            "🖼",
            "Inserisci immagine",
            self._image
        )

        self._add_button(
            layout,
            "table",
            "⊞",
            "Inserisci tabella",
            self._table
        )

        self._add_button(
            layout,
            "horizontal_rule",
            "—",
            "Inserisci linea orizzontale",
            self._horizontal_rule,
        )

        self._add_button(
            layout,
            "code_block",
            "</>",
            "Inserisci blocco di codice",
            self._code_block,
        )

    def _add_preview_button(self, layout):
        self._add_button(
            layout,
            "preview",
            "👁",
            "Anteprima Markdown",
            self._preview
        )

    def _add_separator(self, layout):
        separator = QWidget(self)

        separator.setFixedWidth(1)
        separator.setFixedHeight(22)
        separator.setObjectName("markdownToolbarSeparator")

        layout.addWidget(separator)

    def _add_button(
        self,
        layout,
        key,
        text,
        tooltip,
        callback,
        icon=None,
    ):
        button = QToolButton(self)

        if icon is not None:
            button.setIcon(icon)
        else:
            button.setText(text)
        button.setToolTip(tooltip)
        button.setStatusTip(tooltip)
        button.setObjectName(
            f"markdownToolButton_{key}"
        )

        button.setAutoRaise(True)
        # I pulsanti non devono prendere il focus: la selezione QScintilla
        # deve restare attiva mentre si applica la formattazione Markdown.
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        button.setCursor(
            Qt.CursorShape.PointingHandCursor
        )

        button.clicked.connect(callback)

        layout.addWidget(button)

        self._buttons[key] = button

        return button

    def _call_editor(self, method_name, *args):
        """Chiama un metodo markdown_* sull'editor."""
        if self.editor is None:
            return False

        method = getattr(
            self.editor,
            method_name,
            None,
        )

        if not callable(method):
            return False

        try:
            result = method(*args)
        except Exception:
            return False

        return True if result is None else bool(result)

    def _bold(self):
        return self._call_editor(
            "markdown_bold",
        )

    def _italic(self):
        return self._call_editor(
            "markdown_italic",
        )

    def _underline(self):
        return self._call_editor(
            "markdown_underline",
        )

    def _strikethrough(self):
        return self._call_editor(
            "markdown_strikethrough",
        )

    def _inline_code(self):
        return self._call_editor(
            "markdown_inline_code",
        )

    def _superscript(self):
        return self._call_editor(
            "markdown_superscript",
        )

    def _subscript(self):
        return self._call_editor(
            "markdown_subscript",
        )

    def _heading(self, level):
        return self._call_editor(
            "markdown_heading",
            level,
        )

    def _bullet_list(self):
        return self._call_editor(
            "markdown_bullet_list",
        )

    def _numbered_list(self):
        return self._call_editor(
            "markdown_numbered_list",
        )

    def _checklist(self):
        return self._call_editor(
            "markdown_checklist",
        )

    def _quote(self):
        return self._call_editor(
            "markdown_quote",
        )

    def _link(self):
        return self._call_editor(
            "markdown_link",
        )

    def _image(self):
        return self._call_editor(
            "markdown_image",
        )

    def _table(self):
        return self._call_editor(
            "markdown_table",
        )

    def _horizontal_rule(self):
        return self._call_editor(
            "markdown_horizontal_rule",
        )

    def _code_block(self):
        return self._call_editor(
            "markdown_code_block",
        )

    def _preview(self):
        self.previewRequested.emit()

    def button(self, key):
        """
        Restituisce un pulsante della toolbar tramite il suo identificativo.
        """
        return self._buttons.get(key)
