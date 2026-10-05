from __future__ import annotations

import json
import os
from typing import Any

from qgis.PyQt.QtCore import QLocale


class I18n:
    SUPPORTED = ("it", "en", "de", "fr", "es")
    DEFAULT_LANGUAGE = "en"
    AUTO_LANGUAGE = "auto"

    def __init__(self, settings: Any) -> None:
        self.settings = settings
        configured = self.settings.get("language", self.AUTO_LANGUAGE)
        self.locale = self._normalize_language(configured)
        self.data: dict[str, str] = {}
        self.load(self.locale)

    @classmethod
    def _normalize_language(cls, code: Any) -> str:
        if code is None:
            return cls.AUTO_LANGUAGE

        value = str(code).strip().lower()

        if not value:
            return cls.AUTO_LANGUAGE

        if value == cls.AUTO_LANGUAGE:
            return cls.AUTO_LANGUAGE

        value = value.replace("-", "_").split("_", 1)[0]

        if value in cls.SUPPORTED:
            return value

        return cls.AUTO_LANGUAGE

    def code(self) -> str:
        """
        Restituisce il codice della lingua effettivamente utilizzata.
        """
        if self.locale in self.SUPPORTED:
            return self.locale

        system_locale = QLocale.system().name() or self.DEFAULT_LANGUAGE
        detected = system_locale.replace("-", "_").split("_", 1)[0].lower()

        if detected in self.SUPPORTED:
            return detected

        return self.DEFAULT_LANGUAGE

    def _translation_path(self, language: str) -> str:
        root = os.path.abspath(
            os.path.join(
                os.path.dirname(os.path.dirname(__file__)),
                "translations",
            )
        )
        return os.path.join(root, f"{language}.json")

    def _read_translation_file(self, language: str) -> dict[str, str]:
        path = self._translation_path(language)

        if not os.path.isfile(path):
            return {}

        try:
            with open(path, "r", encoding="utf-8") as handle:
                raw_data = json.load(handle)
        except (OSError, UnicodeError, json.JSONDecodeError):
            return {}

        if not isinstance(raw_data, dict):
            return {}

        result: dict[str, str] = {}

        for key, value in raw_data.items():
            if isinstance(key, str) and isinstance(value, str):
                result[key] = value

        return result

    def load(self, code: str = AUTO_LANGUAGE) -> None:
        """
        Carica il catalogo della lingua richiesta.

        Se il catalogo non esiste o non è valido, viene utilizzato
        il catalogo inglese come fallback.
        """
        requested = self._normalize_language(code)
        self.locale = requested

        actual = self.code()
        data = self._read_translation_file(actual)

        if not data and actual != self.DEFAULT_LANGUAGE:
            data = self._read_translation_file(self.DEFAULT_LANGUAGE)
            actual = self.DEFAULT_LANGUAGE

        self.data = data

    def tr(self, key: str, default: str | None = None) -> str:
        """
        Traduce una chiave.

        Se la chiave non esiste nel catalogo, viene restituito:
        - `default`, se specificato;
        - la chiave stessa, altrimenti.
        """
        if not isinstance(key, str):
            key = str(key)

        if key in self.data:
            return self.data[key]

        if default is not None:
            return default

        return key

    def set_language(self, code: str) -> None:
        """
        Imposta e salva la lingua dell'IDE.
        """
        normalized = self._normalize_language(code)

        if normalized != self.AUTO_LANGUAGE and normalized not in self.SUPPORTED:
            normalized = self.DEFAULT_LANGUAGE

        self.settings.set("language", normalized)
        self.load(normalized)

    def language(self) -> str:
        """
        Restituisce la lingua configurata dall'utente.
        """
        return self.locale

    def available_languages(self) -> tuple[str, ...]:
        """
        Restituisce le lingue supportate dall'IDE.
        """
        return self.SUPPORTED

    def translation_keys(self, language: str) -> frozenset[str]:
        """
        Restituisce le chiavi presenti nel catalogo indicato.
        """
        normalized = self._normalize_language(language)

        if normalized == self.AUTO_LANGUAGE:
            normalized = self.DEFAULT_LANGUAGE

        return frozenset(
            self._read_translation_file(normalized).keys()
        )
