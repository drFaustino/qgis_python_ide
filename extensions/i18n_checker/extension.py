"""Controllo chiavi di traduzione: incrocia le chiavi usate nel codice
(self._t("...")) con i file translations/*.json e segnala mancanti
o orfane per ogni lingua.
"""

import json
import os
import re

from qgis.PyQt.QtGui import QAction
from qgis.PyQt.QtWidgets import QTextBrowser, QVBoxLayout, QDialog, QDialogButtonBox, QMessageBox

MESSAGES = {
    "it": {
        "menu": "🌐 Controlla traduzioni i18n",
        "title": "Controllo traduzioni i18n",
        "used_missing": "Chiavi usate ma mancanti nei file di traduzione",
        "lang_missing": "Chiavi assenti in una lingua",
        "orphans": "Chiavi presenti nei JSON ma non usate nel codice",
        "ok": "Nessun problema rilevato: chiavi usate e traduzioni allineate.",
        "scan_error": "Errore durante la scansione",
        "summary": "Chiavi usate nel codice: {used} — Lingue: {langs}",
        "not_found": "Cartella traduzioni non trovata nel progetto (cercata in resources/i18n, resources/translations, translations, i18n).",
    },
    "en": {
        "menu": "🌐 Check i18n translations",
        "title": "i18n translation check",
        "used_missing": "Keys used in code but missing from translation files",
        "lang_missing": "Keys missing in one language",
        "orphans": "Keys present in JSON but unused in code",
        "ok": "No issues: used keys and translations are aligned.",
        "scan_error": "Error while scanning",
        "summary": "Keys used in code: {used} — Languages: {langs}",
        "not_found": "Translations folder not found in the project (searched in resources/i18n, resources/translations, translations, i18n).",
    },
}

KEY_RE = re.compile(
    r"""(?:self\.)?_t\(\s*["']([\w.\-]+)["']"""
)


from qgis_python_ide.core.ext_i18n import ExtensionBase


class I18nCheckerExtension(ExtensionBase):
    name = "i18n Checker"
    actions = []

    def __init__(self):
        super().__init__()

    def _project_root(self):
        """Radice del PROGETTO aperto nell'IDE (non del plugin IDE)."""
        try:
            root = getattr(
                self._window, "project_root", ""
            )
            if root and os.path.isdir(root):
                return root
            return self._window.settings.get(
                "project_dir", ""
            )
        except Exception:
            return ""

    def _plugin_root(self):
        # .../qgis_python_ide/extensions/i18n_checker/extension.py
        return os.path.dirname(
            os.path.dirname(
                os.path.dirname(os.path.abspath(__file__))
            )
        )

    def _collect_used_keys(self, root):
        keys = set()

        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [
                d
                for d in dirnames
                if d not in ("__pycache__", ".git", "i18n")
            ]

            for filename in filenames:
                if not filename.endswith(".py"):
                    continue

                path = os.path.join(dirpath, filename)

                try:
                    with open(
                        path, "r", encoding="utf-8",
                        errors="replace",
                    ) as handle:
                        content = handle.read()

                    for match in KEY_RE.finditer(content):
                        keys.add(match.group(1))

                except OSError:
                    continue

        return keys

    def _run_check(self):
        try:
            root = self._project_root()

            if not root or not os.path.isdir(root):
                # Nessun progetto aperto: avviso esplicito, tradotto
                # nella lingua corrente dell'IDE.
                QMessageBox.warning(
                    self._window,
                    self.tr("title"),
                    self.tr("no_project"),
                )
                return

            # La cartella delle traduzioni puo' trovarsi in piu'
            # posizioni convenzionali all'interno del progetto.
            candidates = (
                os.path.join(root, "resources", "i18n"),
                os.path.join(root, "resources", "translations"),
                os.path.join(root, "translations"),
                os.path.join(root, "i18n"),
            )

            translations_dir = next(
                (
                    candidate
                    for candidate in candidates
                    if os.path.isdir(candidate)
                ),
                None,
            )

            if translations_dir is None:
                self._show(self.tr("not_found"))
                return

            used = self._collect_used_keys(root)

            languages = {}

            for filename in sorted(
                os.listdir(translations_dir)
            ):
                if filename.endswith(".json"):
                    lang = filename[:-5]

                    try:
                        with open(
                            os.path.join(
                                translations_dir, filename
                            ),
                            "r",
                            encoding="utf-8",
                        ) as handle:
                            languages[lang] = set(
                                json.load(handle).keys()
                            )
                    except (OSError, ValueError):
                        continue

            html_lines = [
                "<h2>" + self.tr("title") + "</h2>",
                "<p>"
                + self.tr("summary").replace(
                    "{used}", str(len(used))
                ).replace(
                    "{langs}", ", ".join(sorted(languages))
                )
                + "</p>",
            ]

            problems = 0

            # Chiavi usate ma totalmente assenti da tutti i JSON
            all_keys = set().union(*languages.values()) if languages else set()
            missing_everywhere = sorted(used - all_keys)

            if missing_everywhere:
                problems += len(missing_everywhere)
                html_lines.append(
                    "<h3 style='color:#c0392b'>"
                    + self.tr("used_missing")
                    + f" ({len(missing_everywhere)})</h3><ul>"
                )
                for key in missing_everywhere:
                    html_lines.append(f"<li><code>{key}</code></li>")
                html_lines.append("</ul>")

            # Chiavi mancanti in una specifica lingua
            per_lang = []
            for lang in sorted(languages):
                missing = sorted(
                    used - languages[lang]
                )
                if missing:
                    per_lang.append((lang, missing))

            if per_lang:
                html_lines.append(
                    "<h3 style='color:#b8860b'>"
                    + self.tr("lang_missing")
                    + "</h3>"
                )
                for lang, missing in per_lang:
                    problems += len(missing)
                    html_lines.append(
                        f"<h4>{lang} ({len(missing)})</h4><ul>"
                    )
                    for key in missing[:40]:
                        html_lines.append(
                            f"<li><code>{key}</code></li>"
                        )
                    if len(missing) > 40:
                        html_lines.append(
                            f"<li>… +{len(missing) - 40}</li>"
                        )
                    html_lines.append("</ul>")

            # Chiavi orfane
            orphans = sorted(all_keys - used)
            if orphans:
                html_lines.append(
                    "<h3 style='color:#7f8c8d'>"
                    + self.tr("orphans")
                    + f" ({len(orphans)})</h3><ul>"
                )
                for key in orphans[:60]:
                    html_lines.append(
                        f"<li><code>{key}</code></li>"
                    )
                if len(orphans) > 60:
                    html_lines.append(
                        f"<li>… +{len(orphans) - 60}</li>"
                    )
                html_lines.append("</ul>")

            if problems == 0:
                html_lines.append(
                    "<p style='color:#27ae60'><b>"
                    + self.tr("ok")
                    + "</b></p>"
                )

            self._show("".join(html_lines))

        except Exception as error:
            try:
                self._window.log.append(
                    f"i18n Checker: {self.tr('scan_error')}: {error}",
                    "WARNING",
                )
            except Exception:  # nosec B110 -- guardia difensiva UI
                pass

    def _show(self, html):
        dialog = QDialog(self._window)
        dialog.setWindowTitle(self.tr("title"))
        dialog.resize(640, 520)

        layout = QVBoxLayout(dialog)

        view = QTextBrowser(dialog)
        view.setHtml(html)
        layout.addWidget(view, 1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Close,
            parent=dialog,
        )
        buttons.rejected.connect(dialog.reject)
        buttons.accepted.connect(dialog.accept)
        layout.addWidget(buttons)

        dialog.exec()

    def register(self, window):
        self._window = window


# ------------------------------------------------------------------
# Contratto del modulo (usato da ExtensionManager)
# ------------------------------------------------------------------

_INSTANCE = I18nCheckerExtension()


def _do_check():
    _INSTANCE._run_check()


_action_check = QAction("🌐 Controlla traduzioni i18n", None)
_action_check.triggered.connect(_do_check)

_INSTANCE.actions = [_action_check]



def _warn_missing_catalog(window):
    """Segnala nel log se manca il catalogo per la lingua corrente."""
    if not _INSTANCE.has_catalog():
        try:
            window.log.append(
                "I18N Checker: "
                "nessun catalogo translations/"
                + _INSTANCE._lang()
                + ".json — uso i messaggi inline.",
                "WARNING",
            )
        except Exception:  # nosec B110 -- guardia difensiva UI
            pass

def register(window):
    _warn_missing_catalog(window)
    _action_check.setText(
        _INSTANCE.tr("menu")
    )
    _action_check.setIcon(_INSTANCE.icon("i18n"))
    _INSTANCE.register(window)


def retranslate():
    """Aggiorna testi e icone delle azioni nella lingua corrente."""
    _action_check.setText(_INSTANCE.tr("menu"))
    _action_check.setIcon(_INSTANCE.icon("i18n"))


def create_extension():
    return _INSTANCE
