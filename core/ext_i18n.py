"""Supporto traduzioni per le estensioni (sottoplugin) dell'IDE.

Ogni estensione può tradurre i propri messaggi in tutte le lingue
supportate dall'IDE (it, en, de, es, fr) in due modi:

1. File ``translations/<lingua>.json`` dentro la cartella dell'estensione
   (es. ``extensions/local_history/translations/de.json``);
2. Dizionario inline ``MESSAGES`` nella classe come fallback.

La lingua corrente segue quella configurata nell'IDE (``window.i18n``);
se l'estensione non è ancora collegata alla finestra viene usata la
lingua di sistema di Qt.
"""

from __future__ import annotations

import json
import os
import sys

from qgis.PyQt.QtCore import QLocale
from qgis.PyQt.QtGui import QIcon

SUPPORTED = ("it", "en", "de", "fr", "es")
DEFAULT_LANGUAGE = "en"


def detect_language() -> str:
    """Lingua di sistema rilevata da Qt, limitata alle lingue supportate."""
    try:
        name = QLocale.system().name() or ""
        code = name.replace("-", "_").split("_", 1)[0].lower()

        if code in SUPPORTED:
            return code
    except Exception:  # nosec B110 -- guardia difensiva UI
        pass

    return DEFAULT_LANGUAGE


class ExtensionBase:
    """Classe base opzionale per le estensioni con traduzioni multilingua.

    Le sottoclassi possono definire ``MESSAGES = {"it": {...}, "en": {...}}``
    e/o fornire i file ``translations/<lingua>.json``. La traduzione si
    ottiene con ``self.tr("chiave")``.
    """

    name = "Extension"
    actions: list = []

    #: Fallback inline: {"it": {"chiave": "testo"}, "en": {...}, ...}
    MESSAGES: dict = {}

    def __init__(self) -> None:
        self._window = None
        self._catalog_cache: dict = {}

    # ------------------------------------------------------------------
    # Lingua corrente
    # ------------------------------------------------------------------

    def _lang(self) -> str:
        """Lingua attiva: quella dell'IDE, altrimenti quella di sistema."""
        if self._window is not None:
            try:
                code = self._window.i18n.code()

                if code in SUPPORTED:
                    return code
            except Exception:  # nosec B110 -- guardia difensiva UI
                pass

        return detect_language()

    # ------------------------------------------------------------------
    # Cataloghi
    # ------------------------------------------------------------------

    def _extension_dir(self) -> str:
        """Cartella che contiene il file extension.py della sottoclasse."""
        try:
            module_file = sys.modules[
                type(self).__module__
            ].__file__
        except (KeyError, AttributeError):
            return os.path.dirname(os.path.abspath(__file__))

        if module_file:
            return os.path.dirname(os.path.abspath(module_file))

        return os.path.dirname(os.path.abspath(__file__))

    def _load_catalog(self, language: str) -> dict:
        """Carica (con cache) il catalogo JSON della lingua richiesta."""
        if language in self._catalog_cache:
            return self._catalog_cache[language]

        path = os.path.join(
            self._extension_dir(),
            "translations",
            f"{language}.json",
        )

        catalog: dict = {}

        if os.path.isfile(path):
            try:
                with open(path, "r", encoding="utf-8") as handle:
                    raw = json.load(handle)

                if isinstance(raw, dict):
                    catalog = {
                        str(key): str(value)
                        for key, value in raw.items()
                    }
            except (OSError, UnicodeError, ValueError):
                catalog = {}

        self._catalog_cache[language] = catalog
        return catalog

    def icon(self, name: str) -> QIcon:
        """Icona del tema dell'IDE dalla cartella ``icons/`` del plugin.

        Uso nelle estensioni: ``action.setIcon(self.icon("history"))``.
        """
        base = os.path.dirname(
            os.path.dirname(os.path.abspath(__file__))
        )
        path = os.path.join(base, "icons", f"{name}.svg")

        return QIcon(path)

    def has_catalog(self, language: str | None = None) -> bool:
        """True se esiste il file translations/<lingua>.json dell'estensione."""
        if language is None:
            language = self._lang()

        return bool(self._load_catalog(language))

    def reload_catalogs(self) -> None:
        """Svuota la cache dei cataloghi (es. dopo modifiche ai JSON)."""
        self._catalog_cache.clear()

    # ------------------------------------------------------------------
    # Traduzione
    # ------------------------------------------------------------------

    def tr(self, key: str) -> str:
        """
        Traduce ``key`` nella lingua corrente.

        Risoluzione: catalogo JSON della lingua → ``MESSAGES[lingua]`` →
        ``MESSAGES[en]`` → la chiave stessa.
        """
        language = self._lang()

        text = self._load_catalog(language).get(key)

        if text is not None:
            return text

        inline = self.MESSAGES.get(language, {})
        text = inline.get(key)

        if text is not None:
            return text

        text = self.MESSAGES.get(DEFAULT_LANGUAGE, {}).get(key)

        if text is not None:
            return text

        return key

    # ------------------------------------------------------------------
    # Ciclo di vita
    # ------------------------------------------------------------------

    def attach(self, window) -> None:
        """Collega l'estensione alla finestra principale dell'IDE.

        L'IDE chiama il ``register(window)`` definito nel modulo
        ``extension.py``; le sottoclassi possono usare questo metodo
        come comodo interno, per esempio:
        ``def register(window): MiaEstensione._instance.attach(window)``.
        """
        self._window = window
