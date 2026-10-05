from __future__ import annotations

import os
import re

from qgis.PyQt.QtCore import Qt, QTimer
from qgis.PyQt.QtGui import QFont, QTextCursor, QFontDatabase
from qgis.PyQt.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QPlainTextEdit,
    QTextBrowser,
    QSplitter,
    QMenu,
)
from qgis.gui import QgsCodeEditorPython
from qgis.core import QgsApplication

try:
    from qgis.PyQt.Qsci import (
        QsciScintilla,
        QsciLexerXML,
        QsciLexerCSS,
        QsciLexerMarkdown,
        QsciLexerProperties,
    )
except Exception:
    QsciScintilla = None
    QsciLexerXML = None
    QsciLexerCSS = None
    QsciLexerMarkdown = None
    QsciLexerProperties = None

from ..core.formatters import language_for_suffix
from .markdown_toolbar import MarkdownToolbar



class GenericCodeEditor(
    QsciScintilla if QsciScintilla is not None else QPlainTextEdit
):
    @staticmethod
    def qgis_code_font():
        """Restituisce il carattere configurato da QGIS per gli editor di codice."""
        try:
            return QFont(QgsCodeEditorPython.getMonospaceFont())
        except Exception:
            try:
                return QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
            except Exception:
                font = QFont()
                font.setStyleHint(QFont.StyleHint.Monospace)
                return font

    """Editor generico per XML, QSS, Markdown, INI, testo e altri formati."""

    def __init__(self, parent=None, language="Text"):
        super().__init__(parent)
        self.completion_callback = None
        self.documentation_callback = None
        self.translation_callback = None

        # QScintilla mantiene la selezione anche quando un pulsante della
        # toolbar riceve il mouse, ma in alcune versioni Qt/QScintilla la
        # selezione interrogabile dal widget può risultare temporaneamente
        # vuota durante il click. Conserviamo quindi sempre l'ultima
        # selezione reale del documento come fallback.
        # Ultima selezione/cursore dell'utente in coordinate QScintilla
        # (riga/colonna). Non usiamo la posizione del focus della toolbar come
        # riferimento: il testo deve restare esattamente sulla riga/colonna
        # in cui l'utente lo ha selezionato.
        self._markdown_last_selection = None  # (line1, col1, line2, col2)
        self._markdown_last_cursor = (0, 0)
        self._markdown_selection_snapshot = None  # (text, line1, col1, line2, col2)
        self._markdown_tracking_ready = False

        if QsciScintilla is not None:
            self._configure_scintilla(language)
        else:
            self._configure_plain_text()

        self._install_markdown_selection_tracking()

    def _install_markdown_selection_tracking(self):
        """Tiene una copia dell'ultima selezione/cursore valida.

        Serve soprattutto quando si preme un pulsante della toolbar: il
        click può trasferire temporaneamente il focus senza che QScintilla
        esponga la selezione tramite hasSelectedText()/getSelection().
        """
        try:
            if hasattr(self, "selectionChanged"):
                self.selectionChanged.connect(self._remember_markdown_selection)
            if hasattr(self, "cursorPositionChanged"):
                self.cursorPositionChanged.connect(self._remember_markdown_cursor)
        except Exception:  # nosec B110 -- guardia difensiva UI
            pass
        self._remember_markdown_selection()
        self._remember_markdown_cursor()
        self._markdown_tracking_ready = True

    def _remember_markdown_cursor(self, *args):
        try:
            line, column = self.getCursorPosition()
            self._markdown_last_cursor = (int(line), int(column))
        except Exception:  # nosec B110 -- guardia difensiva UI
            pass

    def _remember_markdown_selection(self, *args):
        try:
            if self.hasSelectedText():
                sl, sc, el, ec = self.getSelection()
                self._markdown_last_selection = (
                    int(sl), int(sc), int(el), int(ec)
                )
                self._markdown_selection_snapshot = (
                    self.text(), int(sl), int(sc), int(el), int(ec)
                )
                self._markdown_last_cursor = (int(el), int(ec))
        except Exception:  # nosec B110 -- guardia difensiva UI
            pass

    def focusOutEvent(self, event):
        """Cattura la selezione *prima* che un pulsante della toolbar prenda il focus.

        QScintilla/Qt può collassare temporaneamente la selezione quando il
        mouse passa dall'editor a un QToolButton. La formattazione Markdown
        deve però usare esattamente l'intervallo che l'utente aveva
        selezionato, comprese riga e colonna.
        """
        try:
            if self.hasSelectedText():
                sl, sc, el, ec = self.getSelection()
                self._markdown_last_selection = (
                    int(sl), int(sc), int(el), int(ec)
                )
                self._markdown_selection_snapshot = (
                    self.text(), int(sl), int(sc), int(el), int(ec)
                )
            else:
                line, column = self.getCursorPosition()
                self._markdown_last_cursor = (int(line), int(column))
        except Exception:  # nosec B110 -- guardia difensiva UI
            pass
        super().focusOutEvent(event)

    def mousePressEvent(self, event):
        # Il mouse sul documento è un'azione dell'utente: la selezione
        # precedente non deve essere riutilizzata se l'utente sta cliccando
        # altrove. Dopo l'evento, selectionChanged registrerà eventualmente
        # la nuova selezione. Un click sulla toolbar non passa da qui.
        try:
            self._clear_markdown_selection_cache()
        except Exception:  # nosec B110 -- guardia difensiva UI
            pass
        super().mousePressEvent(event)
        try:
            self._remember_markdown_selection()
            self._remember_markdown_cursor()
        except Exception:  # nosec B110 -- guardia difensiva UI
            pass

    def _clear_markdown_selection_cache(self):
        self._markdown_last_selection = None
        self._markdown_selection_snapshot = None

    def _configure_scintilla(self, language):
        """Configura QScintilla senza dipendere da enum non disponibili."""
        try:
            self.setUtf8(True)
        except Exception:
            self._log_configuration_error("setUtf8")

        number_margin = self._number_margin_enum()

        if number_margin is not None:
            try:
                self.setMarginType(0, number_margin)
                self.setMarginWidth(0, 42)
                self.setMarginLineNumbers(0, True)
            except Exception:
                self._log_configuration_error("numero righe")

        try:
            brace_mode = self._scintilla_enum(
                "BraceMatch",
                "SloppyBraceMatch",
            )

            if brace_mode is not None:
                self.setBraceMatching(brace_mode)
        except Exception:
            self._log_configuration_error("brace matching")

        try:
            self.setAutoIndent(True)
        except Exception:
            self._log_configuration_error("auto indent")

        try:
            self.setIndentationsUseTabs(False)
        except Exception:
            self._log_configuration_error("indentazione")

        try:
            self.setIndentationWidth(2)
        except Exception:
            self._log_configuration_error("larghezza indentazione")

        # Usa sempre il carattere configurato nell'Editor Codice di QGIS.
        font = self.qgis_code_font()
        try:
            self.setFont(font)
        except Exception:  # nosec B110 -- guardia difensiva UI
            pass

        self._set_lexer(language)
        try:
            lexer = self.lexer()
            if lexer is not None:
                lexer.setDefaultFont(font)
                lexer.setFont(font, -1)
        except Exception:  # nosec B110 -- guardia difensiva UI
            pass

    def _configure_plain_text(self):
        """Configura il fallback QPlainTextEdit."""
        font = self.qgis_code_font()
        self.setFont(font)

        try:
            self.setTabStopDistance(
                4 * font.pointSizeF(),
            )
        except Exception:
            self._log_configuration_error(
                "tab stop",
            )

    def _log_configuration_error(self, operation):
        """Gestisce silenziosamente un errore di configurazione non critico."""
        return None

    def _number_margin_enum(self):
        """Restituisce l'enum NumberMargin compatibile."""
        if QsciScintilla is None:
            return None

        try:
            value = getattr(
                QsciScintilla,
                "NumberMargin",
                None,
            )

            if value is not None:
                return value
        except Exception:
            value = None

        try:
            margin_type = getattr(
                QsciScintilla,
                "MarginType",
                None,
            )

            if margin_type is not None:
                value = getattr(
                    margin_type,
                    "NumberMargin",
                    None,
                )

                if value is not None:
                    return value
        except Exception:
            value = None

        return None

    def _scintilla_enum(self, enum_name, member_name):
        """Cerca un enum QScintilla in più forme compatibili."""
        if QsciScintilla is None:
            return None

        try:
            value = getattr(
                QsciScintilla,
                member_name,
                None,
            )

            if value is not None:
                return value
        except Exception:
            value = None

        try:
            enum_class = getattr(
                QsciScintilla,
                enum_name,
                None,
            )

            if enum_class is not None:
                value = getattr(
                    enum_class,
                    member_name,
                    None,
                )

                if value is not None:
                    return value
        except Exception:
            value = None

        return None

    def _set_lexer(self, language):
        """Imposta il lexer quando quello specifico è disponibile."""
        lexer = None

        try:
            if language == "XML" and QsciLexerXML is not None:
                lexer = QsciLexerXML(self)

            elif language == "QSS" and QsciLexerCSS is not None:
                lexer = QsciLexerCSS(self)

            elif (
                language == "Markdown"
                and QsciLexerMarkdown is not None
            ):
                lexer = QsciLexerMarkdown(self)

            elif (
                language == "INI"
                and QsciLexerProperties is not None
            ):
                lexer = QsciLexerProperties(self)

        except Exception:
            lexer = None

        if lexer is not None:
            try:
                self.setLexer(lexer)
            except Exception:
                self._log_configuration_error("lexer")

    def text(self):
        if (
            QsciScintilla is not None
            and isinstance(self, QsciScintilla)
        ):
            try:
                return super().text()
            except Exception:
                return ""

        return self.toPlainText()

    def setText(self, text):
        text = "" if text is None else str(text)

        if (
            QsciScintilla is not None
            and isinstance(self, QsciScintilla)
        ):
            return super().setText(text)

        return self.setPlainText(text)

    def selectedText(self):
        if (
            QsciScintilla is not None
            and isinstance(self, QsciScintilla)
        ):
            try:
                return super().selectedText()
            except Exception:
                return ""

        return self.textCursor().selectedText()

    def keyPressEvent(self, event):
        if (
            event.key() == Qt.Key.Key_Space
            and event.modifiers()
            & Qt.KeyboardModifier.ControlModifier
        ):
            if self.completion_callback is not None:
                self.completion_callback(self)
                return

        # Trigger automatici di completamento per i linguaggi non Python
        # (XML/.ui, QSS/CSS, JSON, TS...). I suggerimenti restano
        # ignorabili: Esc chiude il popup senza inserire nulla.
        trigger_keys = (
            Qt.Key.Key_Period,
            Qt.Key.Key_Less,      # '<'  -> tag XML
            Qt.Key.Key_Colon,     # ':'  -> valori CSS/JSON
            Qt.Key.Key_QuoteDbl,  # '"'  -> chiavi JSON
            Qt.Key.Key_Slash,     # '/'  -> chiusura tag XML
        )

        if (
            event.key() in trigger_keys
            and self.completion_callback is not None
        ):
            super().keyPressEvent(event)

            QTimer.singleShot(
                20,
                lambda: self.completion_callback(self),
            )

            return

        if (
            event.key() == Qt.Key.Key_F1
            and self.documentation_callback is not None
        ):
            self.documentation_callback(self)
            return

        super().keyPressEvent(event)



class PythonEditor(QgsCodeEditorPython):
    """Editor Python basato sull'editor nativo QGIS."""

    def __init__(
        self,
        parent=None,
        language_service=None,
        completion_callback=None,
        documentation_callback=None,
        translation_callback=None,
        format_callback=None,
        check_callback=None,
        comment_callback=None,
        uncomment_callback=None,
    ):
        try:
            super().__init__(
                parent,
                [],
                mode=self.Mode.ScriptEditor,
                flags=self.Flag.CodeFolding,
            )
        except (TypeError, AttributeError):
            super().__init__(parent)

        self.language_service = language_service
        self.completion_callback = completion_callback
        self.documentation_callback = documentation_callback
        self.translation_callback = translation_callback
        self.format_callback = format_callback
        self.check_callback = check_callback
        self.comment_callback = comment_callback
        self.uncomment_callback = uncomment_callback

        self._configure_python_editor()
        self.setMouseTracking(True)

    def _configure_python_editor(self):
        try:
            self.setUtf8(True)
        except Exception:
            return self._configure_python_editor_fallback()

        try:
            self.setAutoCompletionThreshold(1)
        except Exception:
            self._ignore_configuration_error()

        try:
            self.setAutoIndent(True)
        except Exception:
            self._ignore_configuration_error()

        try:
            self.setIndentationWidth(4)
        except Exception:
            self._ignore_configuration_error()

        try:
            self.setIndentationsUseTabs(False)
        except Exception:
            self._ignore_configuration_error()

        try:
            self.setAutoCompletionSource(self.AcsAll)
        except Exception:
            self._ignore_configuration_error()

        try:
            self.setAutoCompletionCaseSensitivity(False)
        except Exception:
            self._ignore_configuration_error()

        try:
            brace_mode = self._brace_mode()

            if brace_mode is not None:
                self.setBraceMatching(brace_mode)
        except Exception:
            self._ignore_configuration_error()

        try:
            self.setFoldingVisible(True)
        except Exception:
            self._ignore_configuration_error()

        try:
            self.setLineNumbersVisible(True)
        except Exception:
            self._ignore_configuration_error()

        try:
            self.setMarginWidth(0, 44)
        except Exception:
            self._ignore_configuration_error()

    def _configure_python_editor_fallback(self):
        return None

    def _ignore_configuration_error(self):
        return None

    def _brace_mode(self):
        """Restituisce SloppyBraceMatch se disponibile."""
        try:
            value = getattr(
                self,
                "SloppyBraceMatch",
                None,
            )

            if value is not None:
                return value
        except Exception:
            value = None

        if QsciScintilla is not None:
            try:
                value = getattr(
                    QsciScintilla,
                    "SloppyBraceMatch",
                    None,
                )

                if value is not None:
                    return value
            except Exception:
                value = None

        return None

    def _looks_like_python_document(self):
        return True

    def _has_utf8_header(self):
        try:
            first_two = self.text().splitlines()[:2]
        except Exception:
            return False
        return any("coding" in line.lower() and "utf-8" in line.lower() for line in first_two)

    def add_utf8_header(self):
        """Inserisce l'encoding declaration PEP 263 all'inizio del documento."""
        text = self.text()
        if self._has_utf8_header():
            return
        header = "# -*- coding: utf-8 -*-\n"
        if text.startswith("#!"):
            lines = text.splitlines(True)
            text = lines[0] + header + "".join(lines[1:])
        else:
            text = header + text
        self.setText(text)
        try:
            self.setCursorPosition(0, 0)
        except Exception:
            self.update()

    def keyPressEvent(self, event):
        if (
            event.key() == Qt.Key.Key_Space
            and event.modifiers()
            & Qt.KeyboardModifier.ControlModifier
        ):
            if self.completion_callback is not None:
                self.completion_callback(self)
                return

        # Trigger automatici di completamento per i linguaggi non Python
        # (XML/.ui, QSS/CSS, JSON, TS...). I suggerimenti restano
        # ignorabili: Esc chiude il popup senza inserire nulla.
        trigger_keys = (
            Qt.Key.Key_Period,
            Qt.Key.Key_Less,      # '<'  -> tag XML
            Qt.Key.Key_Colon,     # ':'  -> valori CSS/JSON
            Qt.Key.Key_QuoteDbl,  # '"'  -> chiavi JSON
            Qt.Key.Key_Slash,     # '/'  -> chiusura tag XML
        )

        if (
            event.key() in trigger_keys
            and self.completion_callback is not None
        ):
            super().keyPressEvent(event)

            QTimer.singleShot(
                20,
                lambda: self.completion_callback(self),
            )

            return

        if (
            event.key() == Qt.Key.Key_F1
            and self.documentation_callback is not None
        ):
            self.documentation_callback(self)
            return

        super().keyPressEvent(event)



    def _context_text(self, key: str, default: str) -> str:
        callback = self.translation_callback
        if callable(callback):
            try:
                return str(callback(key, default))
            except Exception:  # nosec B110 -- guardia difensiva UI
                pass
        return default

    def select_all_text(self):
        """Seleziona esplicitamente tutto il buffer QGIS/QScintilla."""
        try:
            last_line = max(0, int(self.lines()) - 1)
            last_column = max(0, int(self.lineLength(last_line)))
            self.setSelection(0, 0, last_line, last_column)
            return
        except Exception:
            try:
                self.selectAll()
            except Exception:  # nosec B110 -- guardia difensiva UI
                pass

    def contextMenuEvent(self, event):
        """Menu contestuale completo anche per l'editor Python nativo QGIS."""
        menu = QMenu(self)

        undo = menu.addAction(self._context_text("context.undo", "Undo"))
        undo.triggered.connect(self.undo)
        try:
            undo.setEnabled(bool(self.isUndoAvailable()))
        except Exception:  # nosec B110 -- guardia difensiva UI
            pass

        redo = menu.addAction(self._context_text("context.redo", "Redo"))
        redo.triggered.connect(self.redo)
        try:
            redo.setEnabled(bool(self.isRedoAvailable()))
        except Exception:  # nosec B110 -- guardia difensiva UI
            pass

        menu.addSeparator()

        cut = menu.addAction(self._context_text("context.cut", "Cut"))
        cut.triggered.connect(self.cut)
        copy = menu.addAction(self._context_text("context.copy", "Copy"))
        copy.triggered.connect(self.copy)
        paste = menu.addAction(self._context_text("context.paste", "Paste"))
        paste.triggered.connect(self.paste)
        delete = menu.addAction(self._context_text("context.delete", "Delete"))
        delete.triggered.connect(self.removeSelectedText)

        try:
            selected = bool(self.hasSelectedText())
        except Exception:
            selected = False
        cut.setEnabled(selected)
        copy.setEnabled(selected)
        delete.setEnabled(selected)

        menu.addSeparator()
        select_all = menu.addAction(
            self._context_text("context.select_all", "Select All")
        )
        select_all.triggered.connect(self.select_all_text)

        menu.addSeparator()
        format_action = menu.addAction(
            self._context_text("action.format", "Formatta documento")
        )
        if callable(self.format_callback):
            format_action.triggered.connect(self.format_callback)
        else:
            format_action.setEnabled(False)

        check_action = menu.addAction(
            self._context_text("context.check_syntax", "Controlla sintassi")
        )
        if callable(self.check_callback):
            check_action.triggered.connect(self.check_callback)
        else:
            check_action.setEnabled(False)

        comment_action = menu.addAction(
            self._context_text("context.toggle_comment", "Attiva/disattiva Commento")
        )
        if callable(self.comment_callback):
            comment_action.triggered.connect(self.comment_callback)
        else:
            comment_action.setEnabled(False)

        uncomment_action = menu.addAction(
            self._context_text("context.uncomment", "Decommenta righe selezionate")
        )
        if callable(self.uncomment_callback):
            uncomment_action.triggered.connect(self.uncomment_callback)
        else:
            uncomment_action.setEnabled(False)

        menu.exec(event.globalPos())


class MarkdownEditor(GenericCodeEditor):
    """Editor Markdown specializzato con comandi di formattazione."""

    def __init__(
        self,
        parent=None,
        language="Markdown",
    ):
        super().__init__(
            parent,
            language,
        )

    def _has_selection(self):
        """Indica se esiste una selezione di testo."""
        try:
            return bool(self.hasSelectedText())
        except Exception:
            try:
                return bool(self.selectedText())
            except Exception:
                return False

    def _selected_text(self):
        """Restituisce il testo selezionato."""
        try:
            return self.selectedText()
        except Exception:
            return ""

    def _line_col_to_offset(self, line, column, text=None):
        """Converte una posizione QScintilla in offset Unicode del documento."""
        text = self.text() if text is None else str(text)
        lines = text.splitlines(True)
        line = max(0, int(line))
        column = max(0, int(column))
        if not lines:
            return min(column, len(text))
        if line >= len(lines):
            return len(text)
        return min(sum(len(item) for item in lines[:line]) + column, len(text))

    @staticmethod
    def _offset_to_line_col(offset, text):
        """Converte un offset Unicode in riga/colonna QScintilla."""
        text = "" if text is None else str(text)
        offset = max(0, min(int(offset), len(text)))
        before = text[:offset]
        line = before.count("\n")
        last = before.rfind("\n")
        column = len(before) if last < 0 else len(before) - last - 1
        return line, column

    def _capture_view_state(self):
        """Salva cursore, selezione e scroll prima di una modifica Markdown."""
        text = self.text()
        state = {
            "cursor": 0,
            "selection": None,
            "vscroll": 0,
            "hscroll": 0,
        }
        try:
            line, column = self.getCursorPosition()
            state["cursor"] = self._line_col_to_offset(line, column, text)
        except Exception:  # nosec B110 -- guardia difensiva UI
            pass
        try:
            if self.hasSelectedText():
                sl, sc, el, ec = self.getSelection()
                start = self._line_col_to_offset(sl, sc, text)
                end = self._line_col_to_offset(el, ec, text)
                state["selection"] = (min(start, end), max(start, end))
        except Exception:  # nosec B110 -- guardia difensiva UI
            pass
        try:
            state["vscroll"] = self.verticalScrollBar().value()
            state["hscroll"] = self.horizontalScrollBar().value()
        except Exception:  # nosec B110 -- guardia difensiva UI
            pass
        return state

    def _restore_view_state(self, state, text=None, selection=None, cursor=None):
        """Ripristina posizione senza riportare l'editor all'inizio."""
        text = self.text() if text is None else str(text)
        selection = state.get("selection") if selection is None else selection
        cursor = state.get("cursor", 0) if cursor is None else cursor
        try:
            if selection is not None:
                start, end = selection
                sl, sc = self._offset_to_line_col(start, text)
                el, ec = self._offset_to_line_col(end, text)
                self.setSelection(sl, sc, el, ec)
            else:
                line, column = self._offset_to_line_col(cursor, text)
                self.setCursorPosition(line, column)
            self.verticalScrollBar().setValue(state.get("vscroll", 0))
            self.horizontalScrollBar().setValue(state.get("hscroll", 0))
        except Exception:  # nosec B110 -- guardia difensiva UI
            pass

    def _replace_range_preserving_position(self, start, end, replacement,
                                            selected_inner=None,
                                            cursor_after=None):
        """Sostituisce un intervallo e ripristina selezione/cursore/scroll."""
        text = self.text()
        start = max(0, min(int(start), len(text)))
        end = max(start, min(int(end), len(text)))
        replacement = "" if replacement is None else str(replacement)
        state = self._capture_view_state()

        sl, sc = self._offset_to_line_col(start, text)
        el, ec = self._offset_to_line_col(end, text)
        try:
            self.setSelection(sl, sc, el, ec)
            self.replaceSelectedText(replacement)
        except Exception:
            return False

        new_text = self.text()
        if selected_inner is not None:
            new_selection = (
                start + int(selected_inner[0]),
                start + int(selected_inner[1]),
            )
            new_cursor = None
        elif cursor_after is not None:
            new_selection = None
            new_cursor = start + int(cursor_after)
        else:
            new_selection = None
            new_cursor = start + len(replacement)

        # QScintilla può aggiornare la viewport durante replaceSelectedText;
        # il restore viene eseguito anche nel ciclo Qt successivo.
        self._restore_view_state(
            state,
            new_text,
            selection=new_selection,
            cursor=new_cursor,
        )
        # Aggiorna la cache usando nuovamente coordinate riga/colonna, così
        # una seconda formattazione consecutiva opera sulla stessa posizione.
        try:
            if new_selection is not None:
                a, b = new_selection
                sl, sc = self._offset_to_line_col(a, new_text)
                el, ec = self._offset_to_line_col(b, new_text)
                self._markdown_last_selection = (sl, sc, el, ec)
            else:
                cp = new_cursor if new_cursor is not None else start
                self._markdown_last_cursor = self._offset_to_line_col(cp, new_text)
                self._markdown_last_selection = None
        except Exception:
            self._markdown_last_selection = None
        QTimer.singleShot(
            0,
            lambda: self._restore_view_state(
                state,
                self.text(),
                selection=new_selection,
                cursor=new_cursor,
            ),
        )
        return True

    def _replace_selection(self, text, selected_inner=None, cursor_after=None):
        """Sostituisce la selezione mantenendo posizione, selezione e viewport.

        La selezione viene letta direttamente da QScintilla. Se il click sul
        pulsante della toolbar l'ha resa temporaneamente non interrogabile,
        viene utilizzata l'ultima selezione registrata prima del click.
        """
        text = "" if text is None else str(text)

        selection = None
        if self._has_selection():
            try:
                sl, sc, el, ec = self.getSelection()
                selection = (int(sl), int(sc), int(el), int(ec))
            except Exception:
                selection = None

        # Se il pulsante della toolbar ha temporaneamente sottratto il focus
        # e QScintilla non espone più la selezione, recuperiamo ESATTAMENTE
        # riga e colonna salvate prima del click.
        if selection is None:
            selection = getattr(self, "_markdown_last_selection", None)

        document = self.text()
        if selection is None:
            try:
                line, column = self.getCursorPosition()
                line, column = int(line), int(column)
            except Exception:
                line, column = getattr(self, "_markdown_last_cursor", (0, 0))
            start = self._line_col_to_offset(line, column, document)
            return self._replace_range_preserving_position(
                start,
                start,
                text,
                selected_inner=selected_inner,
                cursor_after=cursor_after,
            )

        sl, sc, el, ec = selection
        start = self._line_col_to_offset(sl, sc, document)
        end = self._line_col_to_offset(el, ec, document)
        if end < start:
            start, end = end, start
        return self._replace_range_preserving_position(
            start,
            end,
            text,
            selected_inner=selected_inner,
            cursor_after=cursor_after,
        )

    def wrap_selection(self, prefix, suffix=None):
        """Applica marcatori alla selezione o al punto del cursore."""
        prefix = "" if prefix is None else str(prefix)
        suffix = prefix if suffix is None else str(suffix)

        if self._has_selection():
            selected = self._selected_text()
            replacement = prefix + selected + suffix
            # Mantieni selezionato il testo originale, non i marcatori.
            return self._replace_selection(
                replacement,
                selected_inner=(len(prefix), len(prefix) + len(selected)),
            )

        # Senza selezione il cursore resta tra prefisso e suffisso.
        return self._replace_selection(
            prefix + suffix,
            cursor_after=len(prefix),
        )

    def markdown_bold(self):
        return self.wrap_selection("**", "**")

    def markdown_italic(self):
        return self.wrap_selection("*", "*")

    def markdown_underline(self):
        return self.wrap_selection("<u>", "</u>")

    def markdown_strikethrough(self):
        return self.wrap_selection("~~", "~~")

    def markdown_inline_code(self):
        return self.wrap_selection("`", "`")

    def markdown_superscript(self):
        return self.wrap_selection("<sup>", "</sup>")

    def markdown_subscript(self):
        return self.wrap_selection("<sub>", "</sub>")

    def _current_line(self):
        """Restituisce numero, colonna e contenuto della riga corrente."""
        try:
            line, column = self.getCursorPosition()
            lines = self.text().splitlines()
            if not lines:
                return line, column, ""
            return line, column, lines[min(max(0, line), len(lines) - 1)]
        except Exception:
            try:
                cursor = self.textCursor()
                block = cursor.block()
                return block.blockNumber(), cursor.positionInBlock(), block.text()
            except Exception:
                return 0, 0, ""

    def _replace_line(self, line_number, new_line):
        """Sostituisce una riga mantenendo cursore, selezione e viewport."""
        old_text = self.text()
        old_lines = old_text.splitlines(True)
        if not old_lines or not (0 <= int(line_number) < len(old_lines)):
            return False
        line_number = int(line_number)
        original = old_lines[line_number]
        ending = ""
        if original.endswith("\r\n"):
            ending = "\r\n"
        elif original.endswith("\n"):
            ending = "\n"
        elif original.endswith("\r"):
            ending = "\r"
        new_lines = list(old_lines)
        new_lines[line_number] = str(new_line) + ending
        new_text = "".join(new_lines)

        state = self._capture_view_state()
        old_start = sum(len(item) for item in old_lines[:line_number])
        new_start = sum(len(item) for item in new_lines[:line_number])
        old_body = original[:-len(ending)] if ending else original
        new_body = str(new_line)

        import difflib
        matcher = difflib.SequenceMatcher(None, old_body, new_body, autojunk=False)
        opcodes = matcher.get_opcodes()

        def map_column(column):
            column = max(0, min(int(column), len(old_body)))
            for tag, i1, i2, j1, j2 in opcodes:
                if i1 <= column <= i2:
                    if tag == "equal":
                        return j1 + column - i1
                    return j1 + min(column - i1, max(0, j2 - j1))
            return len(new_body)

        def map_offset(offset):
            offset = max(0, min(int(offset), len(old_text)))
            old_end = old_start + len(original)
            delta = len(new_lines[line_number]) - len(original)
            if offset < old_start:
                return offset
            if offset > old_end:
                return offset + delta
            return new_start + map_column(min(offset - old_start, len(old_body)))

        cursor_new = map_offset(state.get("cursor", 0))
        selection_new = None
        if state.get("selection") is not None:
            a, b = state["selection"]
            selection_new = (map_offset(a), map_offset(b))

        self._loading = True
        try:
            self.setText(new_text)
        finally:
            self._loading = False
        self._restore_view_state(state, new_text, selection_new, cursor_new)
        QTimer.singleShot(0, lambda: self._restore_view_state(
            state, self.text(), selection_new, cursor_new
        ))
        return True

    def markdown_heading(self, level):
        """
        Applica o rimuove un titolo Markdown
        dalla riga corrente.
        """
        level = max(
            1,
            min(6, int(level)),
        )

        line_number, _, current = (
            self._current_line()
        )

        stripped = current.lstrip()

        existing = re.match(
            r"^(#{1,6})\s+",
            stripped,
        )

        if existing:
            content = stripped[
                len(existing.group(0)):
            ].lstrip()

            if (
                len(existing.group(1))
                == level
            ):
                return self._replace_line(
                    line_number,
                    content,
                )

            return self._replace_line(
                line_number,
                "#" * level
                + " "
                + content,
            )

        return self._replace_line(
            line_number,
            "#" * level
            + " "
            + stripped,
        )

    def _replace_lines_with_prefixes(self, line_prefixes):
        """Applica prefissi alle righe e mantiene selezione/cursore."""
        old_text = self.text()
        old_lines = old_text.splitlines(True)
        if not old_lines:
            return False
        state = self._capture_view_state()
        prefixes = list(line_prefixes)
        while len(prefixes) < len(old_lines):
            prefixes.append("")

        new_lines = []
        for i, raw in enumerate(old_lines):
            prefix = str(prefixes[i] or "")
            new_lines.append(prefix + raw)
        new_text = "".join(new_lines)

        # Mappa ogni offset aggiungendo il prefisso della riga che lo contiene
        # e quelli delle righe precedenti.
        old_starts = []
        pos = 0
        for raw in old_lines:
            old_starts.append(pos)
            pos += len(raw)

        def map_offset(offset):
            offset = max(0, min(int(offset), len(old_text)))
            if not old_lines:
                return offset
            line = 0
            for i, start in enumerate(old_starts):
                if start <= offset:
                    line = i
                else:
                    break
            return offset + sum(len(prefixes[i]) for i in range(line + 1))

        cursor_new = map_offset(state.get("cursor", 0))
        selection_new = None
        if state.get("selection") is not None:
            a, b = state["selection"]
            selection_new = (map_offset(a), map_offset(b))

        self._loading = True
        try:
            self.setText(new_text)
        finally:
            self._loading = False
        self._restore_view_state(state, new_text, selection_new, cursor_new)
        QTimer.singleShot(0, lambda: self._restore_view_state(
            state, self.text(), selection_new, cursor_new
        ))
        return True

    def _selection_lines(self):
        """Restituisce gli estremi delle righe selezionate."""
        if not hasattr(self, "getSelection"):
            return None
        try:
            line_from, _, line_to, _ = self.getSelection()
        except Exception:
            return None
        lines = self.text().splitlines(True)
        if not lines:
            return None
        line_from = max(0, min(int(line_from), len(lines) - 1))
        line_to = max(line_from, min(int(line_to), len(lines) - 1))
        return line_from, line_to, lines

    def _prefix_lines(self, prefix):
        """Aggiunge (o rimuove, se gia' presente) un prefisso sulle righe
        selezionate, preservando esattamente cursore e selezione."""
        def transform(body):
            if body.startswith(prefix):
                return body[len(prefix):], len(prefix)
            return prefix + body, 0

        return self._transform_lines(transform)

    def _transform_lines(self, transform):
        """Applica transform(body) -> (new_body, removed_prefix_len) a
        ogni riga del range selezionato (o riga corrente) e sostituisce
        il documento preservando posizione di cursore e selezione."""
        # Senza selezione getSelection() e' indefinito: usa direttamente
        # la posizione del cursore, altrimenti il prefisso finirebbe
        # sempre sulla prima riga.
        if self.hasSelectedText():
            sl, _sc, el, _ec = self.getSelection()
        else:
            sl, _sc = self.getCursorPosition()
            el = sl

        old_text = self.text()
        old_lines = old_text.split("\n")

        if sl >= len(old_lines):
            return False

        el = min(el, len(old_lines) - 1)

        deltas = [0] * len(old_lines)
        removed = [0] * len(old_lines)
        new_lines = list(old_lines)

        for i in range(sl, el + 1):
            body = old_lines[i]
            new_body, removed_len = transform(body)
            new_lines[i] = new_body
            deltas[i] = len(new_body) - len(body)
            removed[i] = removed_len

        new_text = "\n".join(new_lines)

        # Offset di inizio riga nei testi vecchio e nuovo.
        old_starts = []
        position = 0
        for body in old_lines:
            old_starts.append(position)
            position += len(body) + 1

        new_starts = []
        position = 0
        for body in new_lines:
            new_starts.append(position)
            position += len(body) + 1

        # state["cursor"] e state["selection"] sono OFFSET nel testo
        # VECCHIO (vedi _capture_view_state), non coppie (riga, colonna).
        def map_offset(offset):
            line = 0
            for i in range(len(old_starts) - 1, -1, -1):
                if old_starts[i] <= offset:
                    line = i
                    break
            column = offset - old_starts[line]
            if sl <= line <= el:
                if column < removed[line]:
                    # Il cursore era dentro il prefisso rimosso:
                    # portalo a inizio contenuto riga.
                    return new_starts[line]
                return new_starts[line] + column + deltas[line]
            return new_starts[line] + column

        state = self._capture_view_state()

        if state.get("selection"):
            start_off, end_off = state["selection"]
            return self._replace_range_preserving_position(
                0,
                len(old_text),
                new_text,
                selected_inner=(
                    map_offset(start_off),
                    map_offset(end_off),
                ),
            )

        return self._replace_range_preserving_position(
            0,
            len(old_text),
            new_text,
            cursor_after=map_offset(state["cursor"]),
        )

    def markdown_bullet_list(self):
        return self._prefix_lines("- ")

    def markdown_numbered_list(self):
        """Numerazione sequenziale del blocco selezionato, preservando
        cursore e selezione. Una numerazione esistente viene sostituita."""
        import re as _re
        counter = 0

        def transform(body):
            nonlocal counter
            counter += 1
            stripped = _re.sub(r"^\s*\d+\.\s+", "", body)
            removed = len(body) - len(stripped)
            return f"{counter}. " + stripped, removed

        return self._transform_lines(transform)

    def markdown_checklist(self):
        """Trasforma le righe selezionate in una checklist."""
        return self._prefix_lines(
            "- [ ] ",
        )

    def markdown_quote(self):
        """Trasforma le righe selezionate in citazioni."""
        return self._prefix_lines(
            "> ",
        )

    def markdown_horizontal_rule(self):
        """Inserisce una linea orizzontale nel punto corrente."""
        return self._replace_selection("---\n", cursor_after=4)

    def markdown_code_block(self, language=""):
        """Inserisce un blocco di codice mantenendo la selezione interna."""
        language = "" if language is None else str(language)
        selected = self._selected_text()
        opening = "```" + language + "\n"
        replacement = opening + selected + "\n```\n"
        if selected:
            return self._replace_selection(
                replacement,
                selected_inner=(len(opening), len(opening) + len(selected)),
            )
        return self._replace_selection(
            replacement,
            cursor_after=len(opening),
        )

    def markdown_link(self, url="https://"):
        """Crea un link e mantiene selezionato il testo del link."""
        url = "https://" if url is None else str(url)
        selected = self._selected_text()
        if selected:
            replacement = f"[{selected}]({url})"
            return self._replace_selection(
                replacement,
                selected_inner=(1, 1 + len(selected)),
            )
        replacement = f"[testo]({url})"
        return self._replace_selection(
            replacement,
            selected_inner=(1, 1 + len("testo")),
        )

    def markdown_image(self, url=""):
        """Crea un'immagine e mantiene selezionato il testo alternativo."""
        url = "" if url is None else str(url)
        selected = self._selected_text()
        alt_text = selected or "descrizione"
        replacement = f"![{alt_text}]({url})"
        return self._replace_selection(
            replacement,
            selected_inner=(2, 2 + len(alt_text)),
        )

    def markdown_table(self):
        """Inserisce una tabella mantenendo la posizione del cursore."""
        table = (
            "| Colonna 1 | Colonna 2 |\n"
            "|-----------|-----------|\n"
            "| Valore 1  | Valore 2  |\n"
            "| Valore 3  | Valore 4  |\n"
        )
        return self._replace_selection(table, cursor_after=len(table))


class EditorTab(QWidget):
    """
    Tab editor principale.

    Gestisce:
    - Python
    - Markdown
    - XML
    - QSS/CSS
    - JSON
    - YAML
    - INI/CFG
    - testo semplice
    - salvataggio
    - modifica
    - selezione
    - commento/decommento
    - posizione cursore
    """

    SUPPORTED = {
        ".py",
        ".pyw",
        ".md",
        ".markdown",
        ".qss",
        ".css",
        ".txt",
        ".xml",
        ".ui",
        ".ts",
        ".ini",
        ".cfg",
        ".json",
        ".yaml",
        ".yml",
    }

    def __init__(
        self,
        path=None,
        parent=None,
        language_service=None,
        completion_callback=None,
        documentation_callback=None,
        translation_callback=None,
        format_callback=None,
        check_callback=None,
        comment_callback=None,
        uncomment_callback=None,
        initial_suffix=None,
    ):
        super().__init__(parent)

        self.path = (
            os.path.abspath(path)
            if path
            else None
        )

        self.modified = False
        self.encoding = "utf-8"
        self._loading = False
        self.uncomment_callback = uncomment_callback

        suffix = (
            str(initial_suffix or "").strip().lower()
            or os.path.splitext(self.path or "")[1].lower()
        )
        if suffix and not suffix.startswith("."):
            suffix = "." + suffix

        self.file_suffix = suffix

        self.language = language_for_suffix(
            suffix,
        )

        root = QVBoxLayout(self)

        root.setContentsMargins(
            0,
            0,
            0,
            0,
        )

        if suffix in {
            ".md",
            ".markdown",
        }:
            self._create_markdown_editor(
                root,
            )

        elif suffix in {
            ".py",
            ".pyw",
            "",
        }:
            self._create_python_editor(
                root,
                language_service,
                completion_callback,
                documentation_callback,
                translation_callback,
                format_callback,
                check_callback,
                comment_callback,
                uncomment_callback,
            )

        else:
            self._create_generic_editor(
                root,
                completion_callback,
                documentation_callback,
                translation_callback,
            )

        self._install_comment_helpers()

    def _create_markdown_editor(self, root):
        """Crea editor, toolbar e anteprima Markdown."""
        self.editor = MarkdownEditor(
            self,
            "Markdown",
        )

        self.markdown_toolbar = MarkdownToolbar(
            self.editor,
            self,
        )

        self.preview = QTextBrowser(self)
        try:
            self.preview.setFont(self.editor.qgis_code_font())
        except Exception:  # nosec B110 -- guardia difensiva UI
            pass
        self.preview.document().setUndoRedoEnabled(False)
        self.preview.document().setMaximumBlockCount(0)

        self.preview.setOpenExternalLinks(
            True,
        )
        self.preview.setOpenLinks(True)
        self.preview.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu
        )
        self.preview.customContextMenuRequested.connect(
            self._markdown_preview_context_menu
        )

        split = QSplitter(
            Qt.Orientation.Horizontal,
            self,
        )

        split.addWidget(
            self.editor,
        )

        split.addWidget(
            self.preview,
        )

        split.setSizes(
            [
                800,
                500,
            ],
        )

        root.addWidget(
            self.markdown_toolbar,
        )

        root.addWidget(
            split,
        )

        self.editor.textChanged.connect(
            self._markdown_changed,
        )

        self._setup_markdown_sync()

        self.markdown_toolbar.previewRequested.connect(
            self._toggle_markdown_preview,
        )

    def _markdown_preview_context_menu(self, position):
        """Menu contestuale dell'anteprima Markdown.

        La sincronizzazione è automatica; il comando manuale serve solo come
        fallback per forzare un nuovo rendering senza introdurre un pulsante
        permanente nell'interfaccia.
        """
        menu = self.preview.createStandardContextMenu()
        menu.addSeparator()
        refresh = menu.addAction(
            self._context_text(
                "context.refresh_markdown_preview",
                "Aggiorna anteprima Markdown",
            )
        )
        refresh.triggered.connect(self.sync_markdown_preview)
        menu.exec(self.preview.mapToGlobal(position))

    def _context_text(self, key: str, default: str) -> str:
        """Restituisce una stringa tradotta per il menu contestuale del tab."""
        callback = getattr(self, "translation_callback", None)
        if callable(callback):
            try:
                return str(callback(key, default))
            except Exception:  # nosec B110 -- guardia difensiva UI
                pass
        return default

    @staticmethod
    def _md_inline(value):
        """Formattazione inline con escape totale: nessun tag HTML passa mai
        grezzo al parser Qt, quindi l'anteprima non viene mai troncata."""
        import html

        value = html.escape(value, quote=False)
        code_spans = []

        def _code(match):
            code_spans.append(match.group(1))
            return "\x00%d\x00" % (len(code_spans) - 1)

        value = re.sub(r"`([^`]+)`", _code, value)
        value = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", value)
        value = re.sub(r"__([^_]+)__", r"<strong>\1</strong>", value)
        value = re.sub(r"~~([^~]+)~~", r"<del>\1</del>", value)
        value = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"<em>\1</em>", value)
        value = re.sub(r"(?<!_)_([^_\n]+)_(?!_)", r"<em>\1</em>", value)
        # <u>, <sup>, <sub> inseriti dalla toolbar: rese sicure dopo l'escape
        value = re.sub(
            r"&lt;(u|sup|sub)&gt;(.*?)&lt;/\1&gt;",
            r"<\1>\2</\1>",
            value,
        )

        def _image(match):
            return '<img src="%s" alt="%s" />' % (
                html.escape(match.group(2), quote=True),
                html.escape(match.group(1), quote=True),
            )

        value = re.sub(r"!\[([^\]]*)\]\(([^)\s]+)\)", _image, value)
        value = re.sub(
            r"\[([^\]]+)\]\(([^)\s]+)\)",
            r'<a href="\2">\1</a>',
            value,
        )

        def _restore_code(match):
            return "<code>%s</code>" % html.escape(
                code_spans[int(match.group(1))], quote=False
            )

        value = re.sub("\x00(\\d+)\x00", _restore_code, value)
        return value

    @classmethod
    def _qt_markdown_body(cls, source):
        """Blocchi Markdown: righe, liste, tabelle, codice, titoli.
        Ogni riga del sorgente produce output: nessun troncamento."""
        import html

        lines = source.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        out = []
        in_code = False
        code_lang = ""
        list_mode = None
        paragraph = []
        in_table = False

        def flush_paragraph():
            if paragraph:
                out.append(
                    "<p>%s</p>"
                    % "<br/>".join(cls._md_inline(item) for item in paragraph)
                )
                paragraph.clear()

        def close_list():
            nonlocal list_mode
            if list_mode:
                out.append("</%s>" % list_mode)
                list_mode = None

        def close_table():
            nonlocal in_table
            if in_table:
                out.append("</table>")
                in_table = False

        for line in lines:
            if line.startswith("```"):
                flush_paragraph()
                close_list()
                close_table()
                if not in_code:
                    in_code = True
                    code_lang = html.escape(line[3:].strip(), quote=True)
                    out.append(
                        '<pre><code class="language-%s">' % code_lang
                    )
                else:
                    in_code = False
                    out.append("</code></pre>")
                continue
            if in_code:
                out.append(html.escape(line, quote=False) + "\n")
                continue
            if not line.strip():
                flush_paragraph()
                close_list()
                close_table()
                continue
            match = re.match(r"^(#{1,6})\s+(.*)$", line)
            if match:
                flush_paragraph()
                close_list()
                close_table()
                level = len(match.group(1))
                out.append(
                    "<h%d>%s</h%d>"
                    % (level, cls._md_inline(match.group(2)), level)
                )
                continue
            # Tabella GitHub-flavored
            if line.lstrip().startswith("|") and line.rstrip().endswith("|"):
                flush_paragraph()
                close_list()
                cells = [
                    cell.strip()
                    for cell in line.strip().strip("|").split("|")
                ]
                if all(re.match(r"^:?-{3,}:?$", c) for c in cells if c):
                    continue  # riga separatrice |---|---|
                if not in_table:
                    out.append("<table>")
                    in_table = True
                    tag = "th"
                else:
                    tag = "td"
                out.append(
                    "<tr>%s</tr>" % "".join(
                        "<%s>%s</%s>" % (tag, cls._md_inline(c), tag)
                        for c in cells
                    )
                )
                continue
            match = re.match(r"^\s*[-*+]\s+(?:\[[ xX]\]\s+)?(.*)$", line)
            if match:
                flush_paragraph()
                close_table()
                if list_mode != "ul":
                    close_list()
                    out.append("<ul>")
                    list_mode = "ul"
                out.append("<li>%s</li>" % cls._md_inline(match.group(1)))
                continue
            match = re.match(r"^\s*\d+\.\s+(.*)$", line)
            if match:
                flush_paragraph()
                close_table()
                if list_mode != "ol":
                    close_list()
                    out.append("<ol>")
                    list_mode = "ol"
                out.append("<li>%s</li>" % cls._md_inline(match.group(1)))
                continue
            if re.match(r"^\s*>", line):
                flush_paragraph()
                close_list()
                close_table()
                out.append(
                    "<blockquote>%s</blockquote>"
                    % cls._md_inline(re.sub(r"^\s*>\s?", "", line))
                )
                continue
            if re.match(r"^\s*([-*_])(?:\s*\1){2,}\s*$", line):
                flush_paragraph()
                close_list()
                close_table()
                out.append("<hr/>")
                continue
            close_list()
            close_table()
            paragraph.append(line)

        flush_paragraph()
        close_list()
        close_table()
        if in_code:
            out.append("</code></pre>")
        return "\n".join(out)

    def _render_markdown_html(self, source):
        """Renderizza Markdown in HTML completo, sicuro per Qt e mai troncato."""
        source = "" if source is None else str(source)
        body = self._qt_markdown_body(source)
        font = self.editor.qgis_code_font()
        family = font.family().replace("&", "&amp;").replace('"', "&quot;")
        size = max(1, font.pointSize())
        return """<!doctype html>
<html><head><meta charset="utf-8"><style>
body {{ font-family: "{family}"; font-size: {size}pt; }}
strong, b {{ font-weight: 800; }}
em, i {{ font-style: italic; }}
u {{ text-decoration: underline; }}
del {{ text-decoration: line-through; }}
code, pre {{ font-family: "{family}"; }}
code {{ background-color: #f0f0f0; padding: 0 2px; }}
pre {{ white-space: pre-wrap; background-color: #f0f0f0; padding: 4px; }}
pre code {{ background-color: transparent; padding: 0; }}
p {{ margin: 4px 0; }}
h1, h2, h3, h4, h5, h6 {{ margin: 10px 0 4px 0; }}
blockquote {{ margin: 4px 0; padding-left: 8px;
    border-left: 3px solid #999999; }}
table {{ border-collapse: collapse; margin: 4px 0; }}
td, th {{ border: 1px solid #999999; padding: 2px 6px; }}
hr {{ border: 0; border-top: 1px solid #999999; }}
ul, ol {{ margin: 4px 0; padding-left: 24px; }}
</style></head><body>{body}</body></html>""".format(
            family=family, size=size, body=body
        )

    def sync_markdown_preview(self):
        """Aggiorna l'anteprima Markdown senza troncare il documento."""
        if not hasattr(self, "preview"):
            return

        ratio = self._markdown_scroll_ratio(self.editor)
        cursor_line = 0
        try:
            cursor_line, _ = self.editor.getCursorPosition()
        except Exception:  # nosec B110 -- guardia difensiva UI
            pass

        source = self.editor.text()
        html = self._render_markdown_html(source)
        try:
            if html:
                self.preview.setHtml(html)
            else:
                self.preview.setMarkdown(source)
        except Exception:
            try:
                self.preview.setMarkdown(source)
            except Exception:
                self.preview.setPlainText(source)

        def restore_position():
            # Il layout QTextDocument è pronto solo dopo il ritorno al loop Qt.
            self._set_markdown_scroll_ratio(self.preview, ratio)
            self._sync_markdown_preview_from_line(cursor_line)

        QTimer.singleShot(0, restore_position)

    @staticmethod
    def _markdown_scroll_ratio(widget):
        bar = widget.verticalScrollBar()
        maximum = bar.maximum()
        return (bar.value() / maximum) if maximum > 0 else 0.0

    @staticmethod
    def _set_markdown_scroll_ratio(widget, ratio):
        bar = widget.verticalScrollBar()
        maximum = bar.maximum()
        bar.setValue(round(maximum * max(0.0, min(1.0, float(ratio)))))

    def _sync_markdown_scroll_from_editor(self):
        if getattr(self, "_markdown_syncing", False) or not hasattr(self, "preview"):
            return
        self._markdown_syncing = True
        try:
            ratio = self._markdown_scroll_ratio(self.editor)
            self._set_markdown_scroll_ratio(self.preview, ratio)
        finally:
            self._markdown_syncing = False

    def _sync_markdown_scroll_from_preview(self):
        if getattr(self, "_markdown_syncing", False) or not hasattr(self, "preview"):
            return
        self._markdown_syncing = True
        try:
            ratio = self._markdown_scroll_ratio(self.preview)
            self._set_markdown_scroll_ratio(self.editor, ratio)
            # NON spostare mai il cursore dell'editor in base allo scroll
            # dell'anteprima: la posizione del cursore/selezione resta
            # esattamente dove l'utente (o la formattazione) l'ha messa.
        finally:
            self._markdown_syncing = False

    def _sync_markdown_preview_from_line(self, line):
        try:
            line_count = max(1, int(self.editor.lines()))
            ratio = max(0.0, min(1.0, float(line) / max(1, line_count - 1)))
            self._set_markdown_scroll_ratio(self.preview, ratio)
        except Exception:  # nosec B110 -- guardia difensiva UI
            pass

    def _sync_markdown_preview_from_cursor(self, *args):
        if getattr(self, "_markdown_syncing", False) or not hasattr(self, "preview"):
            return
        try:
            line, _ = self.editor.getCursorPosition()
            self._markdown_syncing = True
            self._sync_markdown_preview_from_line(line)
        finally:
            self._markdown_syncing = False

    def _setup_markdown_sync(self):
        """Collega scroll e cursore dei due pannelli in entrambe le direzioni."""
        self._markdown_syncing = False
        self.editor.verticalScrollBar().valueChanged.connect(self._sync_markdown_scroll_from_editor)
        self.preview.verticalScrollBar().valueChanged.connect(self._sync_markdown_scroll_from_preview)
        if hasattr(self.editor, "cursorPositionChanged"):
            self.editor.cursorPositionChanged.connect(self._sync_markdown_preview_from_cursor)

    def _create_python_editor(
        self,
        root,
        language_service,
        completion_callback,
        documentation_callback,
        translation_callback,
        format_callback,
        check_callback,
        comment_callback,
        uncomment_callback,
    ):
        self.editor = PythonEditor(
            self,
            language_service,
            completion_callback,
            documentation_callback,
            translation_callback,
            format_callback,
            check_callback,
            comment_callback,
            uncomment_callback,
        )

        root.addWidget(
            self.editor,
        )

        self.editor.textChanged.connect(
            self._changed,
        )

    def _create_generic_editor(
        self,
        root,
        completion_callback=None,
        documentation_callback=None,
        translation_callback=None,
    ):
        self.editor = GenericCodeEditor(
            self,
            self.language,
        )

        # Autocompletamento per i linguaggi generici (XML, QSS, CSS,
        # JSON, TS...): stesso popup usato da PythonEditor.
        if completion_callback is not None:
            self.editor.completion_callback = completion_callback

        if documentation_callback is not None:
            self.editor.documentation_callback = documentation_callback

        if translation_callback is not None:
            self.editor.translation_callback = translation_callback

        # Toolbar contestuale StyleToolbar per XML e QSS/CSS.
        try:
            from .style_toolbar import StyleToolbar

            _suffix = (
                os.path.splitext(self.path or "")[1] or ""
            ).lower()

            _flavor = None

            if _suffix in (".xml", ".ui"):
                _flavor = "xml"
            elif _suffix in (".css", ".qss", ".scss"):
                _flavor = "style"

            if _flavor is not None:
                self.style_toolbar = StyleToolbar(
                    self.editor,
                    _flavor,
                    self,
                )
                root.addWidget(
                    self.style_toolbar,
                )
        except Exception:
            self.style_toolbar = None

        root.addWidget(
            self.editor,
        )

        self.editor.textChanged.connect(
            self._changed,
        )

    def _install_comment_helpers(self):
        """
        Prepara le funzionalità di commento.

        Non sono necessari monkey patch sul widget:
        toggle_comment() gestisce direttamente la selezione.
        """
        self._comment_prefix = "#"

    def _changed(self):
        if not self._loading:
            self.modified = True

    def _markdown_changed(self):
        self._changed()

        if hasattr(self, "preview"):
            self.sync_markdown_preview()

    def _toggle_markdown_preview(self):
        """Mostra o nasconde l'anteprima Markdown."""
        if not hasattr(
            self,
            "preview",
        ):
            return

        if self.preview.isVisible():
            self.preview.hide()
            return

        self.sync_markdown_preview()
        self.preview.show()

    def text(self):
        try:
            return self.editor.text()
        except Exception:
            if hasattr(
                self.editor,
                "toPlainText",
            ):
                return self.editor.toPlainText()

            return ""

    def set_text(self, text):
        text = (
            ""
            if text is None
            else str(text)
        )

        self._loading = True

        try:
            self.editor.setText(text)
        finally:
            self._loading = False

        self.modified = False

        if hasattr(self, "preview"):
            self.sync_markdown_preview()

    def selected_text(self):
        try:
            return self.editor.selectedText()
        except Exception:
            return ""

    def replace_text(self, text):
        text = (
            ""
            if text is None
            else str(text)
        )

        if hasattr(
            self.editor,
            "replaceSelectedText",
        ):
            try:
                self.editor.replaceSelectedText(
                    text,
                )

                self.modified = True
                return

            except Exception:
                replacement_done = False

            if replacement_done:
                return

        cursor = None

        if hasattr(
            self.editor,
            "textCursor",
        ):
            try:
                cursor = self.editor.textCursor()
            except Exception:
                cursor = None

        if cursor is not None:
            cursor.insertText(text)
            self.editor.setTextCursor(cursor)
        else:
            self.editor.setText(text)

        self.modified = True

    def cursor_location(self):
        if hasattr(
            self.editor,
            "getCursorPosition",
        ):
            try:
                return self.editor.getCursorPosition()
            except Exception:
                cursor_location = None

            if cursor_location is not None:
                return cursor_location

        if hasattr(
            self.editor,
            "textCursor",
        ):
            try:
                cursor = self.editor.textCursor()

                return (
                    cursor.blockNumber(),
                    cursor.positionInBlock(),
                )

            except Exception:
                cursor = None

        return 0, 0

    def cursor_offset(self):
        """
        Restituisce la posizione assoluta del cursore nel documento.
        """
        editor = self.editor

        if hasattr(editor, "getCursorPosition"):
            try:
                line, column = editor.getCursorPosition()
                text = self.text()
                lines = text.splitlines(True)

                if line <= 0:
                    return max(0, column)

                offset = sum(
                    len(item)
                    for item in lines[:line]
                )

                return max(
                    0,
                    min(
                        offset + column,
                        len(text),
                    ),
                )

            except Exception:
                cursor_position = None

            if cursor_position is not None:
                return cursor_position

        if hasattr(editor, "textCursor"):
            try:
                cursor = editor.textCursor()
                return max(
                    0,
                    min(
                        cursor.position(),
                        len(self.text()),
                    ),
                )
            except Exception:
                cursor = None

            if cursor is not None:
                return max(
                    0,
                    min(
                        cursor.position(),
                        len(self.text()),
                    ),
                )

        return 0

    def select_text_range(self, start, end):
        """
        Seleziona l'intervallo [start, end) nel documento.
        """
        text = self.text()

        start = max(
            0,
            min(int(start), len(text)),
        )

        end = max(
            start,
            min(int(end), len(text)),
        )

        if hasattr(self.editor, "setSelection"):
            try:
                before = text[:start]
                end_position = text[:end]

                start_line = before.count("\n")
                start_newline = before.rfind("\n")

                if start_newline < 0:
                    start_column = len(before)
                else:
                    start_column = (
                        len(before)
                        - start_newline
                        - 1
                    )

                end_line = end_position.count("\n")
                end_newline = end_position.rfind("\n")

                if end_newline < 0:
                    end_column = len(end_position)
                else:
                    end_column = (
                        len(end_position)
                        - end_newline
                        - 1
                    )

                self.editor.setSelection(
                    start_line,
                    start_column,
                    end_line,
                    end_column,
                )

                try:
                    self.editor.ensureLineVisible(
                        start_line,
                    )
                except Exception:
                    line_visible = False
                else:
                    line_visible = True

                return True

            except Exception:
                selection_done = False
            else:
                selection_done = True

            if selection_done:
                return True

        if hasattr(self.editor, "textCursor"):
            try:
                cursor = self.editor.textCursor()

                cursor.setPosition(start)
                cursor.setPosition(
                    end,
                    QTextCursor.MoveMode.KeepAnchor,
                )

                self.editor.setTextCursor(cursor)

                try:
                    self.editor.ensureCursorVisible()
                except Exception:
                    cursor_visible = False
                else:
                    cursor_visible = True

                return True

            except Exception:
                cursor = None

            if cursor is not None:
                return True

        return False

    def selection_offsets(self):
        """Restituisce gli offset assoluti della selezione corrente."""
        text = self.text()

        if hasattr(self.editor, "getSelection"):
            try:
                line_from, col_from, line_to, col_to = self.editor.getSelection()
                if min(line_from, col_from, line_to, col_to) < 0:
                    return None

                lines = text.splitlines(True)

                def offset(line, column):
                    if line <= 0:
                        return max(0, min(column, len(text)))
                    return max(
                        0,
                        min(
                            sum(len(item) for item in lines[:line]) + column,
                            len(text),
                        ),
                    )

                start = offset(line_from, col_from)
                end = offset(line_to, col_to)
                if end < start:
                    start, end = end, start
                return start, end
            except Exception:
                return None

        try:
            cursor = self.editor.textCursor()
            start = cursor.selectionStart()
            end = cursor.selectionEnd()
            if start != end:
                return start, end
        except Exception:
            return None

        return None

    def replace_document_text(self, text):
        """Sostituisce il documento preservando cursore, selezione e scroll."""
        text = "" if text is None else str(text)

        old_text = self.text()
        cursor_line = cursor_col = 0
        selection = None
        scroll_value = 0
        try:
            cursor_line, cursor_col = self.editor.getCursorPosition()
        except Exception:  # nosec B110 -- guardia difensiva UI
            pass
        try:
            scroll_value = self.editor.verticalScrollBar().value()
        except Exception:  # nosec B110 -- guardia difensiva UI
            pass
        try:
            if self.editor.hasSelectedText():
                selection = self.editor.getSelection()
        except Exception:
            selection = None

        self._loading = True
        try:
            self.editor.setText(text)
        finally:
            self._loading = False

        self.modified = True

        try:
            line_count = max(1, int(self.editor.lines()))
            cursor_line = min(max(0, int(cursor_line)), line_count - 1)
            cursor_col = min(max(0, int(cursor_col)), int(self.editor.lineLength(cursor_line)))
            if selection is not None:
                sl, sc, el, ec = selection
                sl = min(max(0, int(sl)), line_count - 1)
                el = min(max(sl, int(el)), line_count - 1)
                sc = min(max(0, int(sc)), int(self.editor.lineLength(sl)))
                ec = min(max(0, int(ec)), int(self.editor.lineLength(el)))
                self.editor.setSelection(sl, sc, el, ec)
            else:
                self.editor.setCursorPosition(cursor_line, cursor_col)
            self.editor.verticalScrollBar().setValue(scroll_value)
        except Exception:  # nosec B110 -- guardia difensiva UI
            pass

        if hasattr(self, "preview"):
            self.sync_markdown_preview()

    def comment(self):
        """Commenta le righe selezionate."""
        self._set_comment_state(True)

    def uncomment(self):
        """Decommenta le righe selezionate."""
        self._set_comment_state(False)

    def _set_comment_state(self, comment):
        if self.language not in {"Python", "Text", "Markdown"}:
            return

        if not hasattr(self.editor, "getSelection"):
            return

        try:
            line_from, _col_from, line_to, _col_to = self.editor.getSelection()
        except Exception:
            return

        lines = self.text().splitlines(True)
        if not lines or line_from < 0 or line_to < 0:
            return

        line_from = max(0, min(line_from, len(lines) - 1))
        line_to = max(line_from, min(line_to, len(lines) - 1))

        for index in range(line_from, line_to + 1):
            raw = lines[index]
            if raw.endswith("\r\n"):
                body, ending = raw[:-2], "\r\n"
            elif raw.endswith("\n"):
                body, ending = raw[:-1], "\n"
            elif raw.endswith("\r"):
                body, ending = raw[:-1], "\r"
            else:
                body, ending = raw, ""

            if not body.strip():
                continue

            indent = re.match(r"^\s*", body).group(0)
            if comment:
                lines[index] = indent + "# " + body[len(indent):] + ending
            else:
                lines[index] = re.sub(r"^(\s*)# ?", r"\1", body) + ending

        self.replace_document_text("".join(lines))

    def replace_text_range(
        self,
        start,
        end,
        replacement,
    ):
        """
        Sostituisce l'intervallo [start, end).
        """
        if not self.select_text_range(start, end):
            return False

        self.replace_text(replacement)
        return True

    def word_under_cursor(self):
        line, column = (
            self.cursor_location()
        )

        lines = self.text().splitlines()

        if (
            line < 0
            or line >= len(lines)
        ):
            return ""

        current_line = lines[line]

        column = max(
            0,
            min(
                column,
                len(current_line),
            ),
        )

        match = re.search(
            r"[A-Za-z_]\w*$",
            current_line[:column],
        )

        return (
            match.group(0)
            if match
            else ""
        )

    def goto_line(
        self,
        line,
        column=0,
    ):
        line = max(
            1,
            int(line),
        )

        column = max(
            0,
            int(column),
        )

        if hasattr(
            self.editor,
            "setCursorPosition",
        ):
            try:
                self.editor.setCursorPosition(
                    line - 1,
                    column,
                )

                self.editor.ensureLineVisible(
                    line - 1,
                )

                return

            except Exception:
                cursor_positioned = False

            if cursor_positioned:
                return

        if hasattr(
            self.editor,
            "textCursor",
        ):
            cursor = self.editor.textCursor()

            cursor.movePosition(
                QTextCursor.MoveOperation.Start,
            )

            for _ in range(
                line - 1,
            ):
                cursor.movePosition(
                    QTextCursor.MoveOperation.Down,
                )

            cursor.movePosition(
                QTextCursor.MoveOperation.Right,
                n=column,
            )

            self.editor.setTextCursor(
                cursor,
            )

            try:
                self.editor.ensureCursorVisible()
            except Exception:
                cursor_visible = False

    def toggle_comment(self):
        """Compatibilità: commenta o decommenta in base allo stato della selezione."""
        if self.language not in {"Python", "Text", "Markdown"}:
            return
        try:
            selection = self.text().splitlines(True)
            if not selection:
                return
            line_from, _c1, line_to, _c2 = self.editor.getSelection()
            selected = selection[max(0, line_from):max(0, line_to) + 1]
            nonblank = [line for line in selected if line.strip()]
            uncomment = bool(nonblank) and all(
                re.match(r"^\s*#", line) for line in nonblank
            )
            self._set_comment_state(not uncomment)
        except Exception:
            return

    def save(self, path=None):
        """
        Salva il contenuto del tab.

        Se path è specificato esegue un Save As
        e aggiorna il percorso associato al tab.
        """
        target = (
            path
            if path is not None
            else self.path
        )

        if not target:
            return False

        target = os.path.abspath(
            os.path.expanduser(
                str(target),
            ),
        )

        parent_dir = os.path.dirname(
            target,
        )

        if parent_dir:
            os.makedirs(
                parent_dir,
                exist_ok=True,
            )

        data = self.text()

        encoding = (
            self.encoding
            or "utf-8"
        )

        try:
            with open(
                target,
                "w",
                encoding=encoding,
                newline="",
            ) as handle:
                handle.write(data)

        except UnicodeEncodeError:
            encoding = "utf-8"

            with open(
                target,
                "w",
                encoding=encoding,
                newline="",
            ) as handle:
                handle.write(data)

        self.path = target
        self.encoding = encoding
        self.modified = False

        return True

    def load(self, path=None):
        """
        Carica un file nel tab.

        Restituisce True se il caricamento è riuscito.
        """
        target = (
            path
            if path is not None
            else self.path
        )

        if not target:
            return False

        target = os.path.abspath(
            os.path.expanduser(
                str(target),
            ),
        )

        if not os.path.isfile(target):
            return False

        encodings = []

        if self.encoding:
            encodings.append(
                self.encoding,
            )

        encodings.extend(
            [
                "utf-8",
                "utf-8-sig",
                "cp1252",
                "latin-1",
            ],
        )

        encodings = list(
            dict.fromkeys(encodings),
        )

        content = None
        used_encoding = None

        for encoding in encodings:
            try:
                with open(
                    target,
                    "r",
                    encoding=encoding,
                    newline="",
                ) as handle:
                    content = handle.read()

                used_encoding = encoding
                break

            except (
                UnicodeDecodeError,
                LookupError,
            ):
                continue

        if content is None:
            return False

        self.path = target
        self.encoding = (
            used_encoding
            or "utf-8"
        )

        suffix = os.path.splitext(
            target,
        )[1].lower()
        self.file_suffix = suffix

        self.language = language_for_suffix(
            suffix,
        )

        self.set_text(content)

        return True

    def is_modified(self):
        return bool(
            self.modified,
        )

    def mark_saved(self):
        self.modified = False


