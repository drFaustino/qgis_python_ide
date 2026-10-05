from __future__ import annotations

import importlib.util
import sys
import os
import re
from dataclasses import dataclass
from types import ModuleType
from typing import Any


@dataclass
class IDEExtension:
    """Estensione caricata dal QGIS Python IDE."""

    name: str
    path: str
    module: ModuleType
    actions: list[Any]


class ExtensionManager:
    """
    Gestore delle estensioni opzionali dell'IDE.

    Struttura prevista:

        extensions/
            nome_estensione/
                extension.py

    Il modulo extension.py deve esporre:

        def create_extension():
            return ExtensionObject(...)
    """

    EXTENSIONS_FOLDER = "extensions"
    ENTRY_FILE = "extension.py"
    MODULE_PREFIX = "qgis_python_ide_ext"

    def __init__(self, root: str) -> None:
        self.root = os.path.abspath(os.path.expanduser(str(root)))
        self.extensions: list[IDEExtension] = []
        self.errors: dict[str, str] = {}

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------

    def discover(self) -> list[IDEExtension]:
        """
        Cerca e carica tutte le estensioni presenti nella cartella
        'extensions'.

        Un'estensione non valida o che genera un errore non blocca
        il caricamento delle altre.
        """
        folder = os.path.join(
            self.root,
            self.EXTENSIONS_FOLDER,
        )

        try:
            os.makedirs(folder, exist_ok=True)
        except OSError as error:
            self.errors["__manager__"] = str(error)
            return list(self.extensions)

        try:
            entries = sorted(
                os.listdir(folder),
                key=str.casefold,
            )
        except OSError as error:
            self.errors["__manager__"] = str(error)
            return list(self.extensions)

        discovered: list[IDEExtension] = []
        self.errors.clear()

        for name in entries:
            if not self._valid_extension_name(name):
                continue

            path = os.path.join(folder, name)

            if not os.path.isdir(path):
                continue

            entry = os.path.join(path, self.ENTRY_FILE)

            if not os.path.isfile(entry):
                continue

            extension = self._load_extension(
                name=name,
                path=path,
                entry=entry,
            )

            if extension is not None:
                discovered.append(extension)

        self.extensions = discovered
        return list(self.extensions)

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------

    def _load_extension(
        self,
        name: str,
        path: str,
        entry: str,
    ) -> IDEExtension | None:
        module_name = self._module_name(name)

        try:
            spec = importlib.util.spec_from_file_location(
                module_name,
                entry,
            )

            if spec is None:
                self.errors[name] = (
                    "Impossibile creare lo spec del modulo."
                )
                return None

            loader = spec.loader

            if loader is None:
                self.errors[name] = (
                    "Loader del modulo non disponibile."
                )
                return None

            module = importlib.util.module_from_spec(spec)

            # Registra il modulo in sys.modules: senza questo passo
            # l'estensione non può risalire alla propria cartella e i
            # file translations/<lingua>.json non verrebbero mai caricati.
            sys.modules[module_name] = module

            loader.exec_module(module)

            factory = getattr(
                module,
                "create_extension",
                None,
            )

            if not callable(factory):
                self.errors[name] = (
                    "Il modulo non espone una funzione "
                    "'create_extension()'."
                )
                return None

            extension_object = factory()

            if extension_object is None:
                self.errors[name] = (
                    "'create_extension()' ha restituito None."
                )
                return None

            actions = getattr(
                extension_object,
                "actions",
                [],
            )

            if actions is None:
                normalized_actions: list[Any] = []
            elif isinstance(actions, (list, tuple)):
                normalized_actions = list(actions)
            else:
                normalized_actions = [actions]

            return IDEExtension(
                name=name,
                path=path,
                module=module,
                actions=normalized_actions,
            )

        except ImportError as error:
            self.errors[name] = (
                f"Dipendenza o import mancante: {error}"
            )
            return None

        except OSError as error:
            self.errors[name] = (
                f"Errore di accesso al file: {error}"
            )
            return None

        except Exception as error:
            self.errors[name] = (
                f"Errore durante il caricamento: {error}"
            )
            return None

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    @staticmethod
    def _valid_extension_name(name: str) -> bool:
        """
        Verifica che il nome della cartella sia valido.

        Sono accettati nomi utilizzabili come identificatori Python
        oppure nomi con trattini/spazi, che verranno normalizzati
        per il nome interno del modulo.
        """
        if not name:
            return False

        if name in {".", ".."}:
            return False

        if name.startswith("."):
            return False

        if os.path.sep in name:
            return False

        if os.path.altsep and os.path.altsep in name:
            return False

        return True

    # ------------------------------------------------------------------
    # Module naming
    # ------------------------------------------------------------------

    @classmethod
    def _module_name(cls, name: str) -> str:
        """
        Genera un nome di modulo Python stabile e sicuro.
        """
        safe_name = re.sub(
            r"\W+",
            "_",
            name,
            flags=re.UNICODE,
        ).strip("_")

        if not safe_name:
            safe_name = "extension"

        if safe_name[0].isdigit():
            safe_name = f"ext_{safe_name}"

        return f"{cls.MODULE_PREFIX}_{safe_name}"

    # ------------------------------------------------------------------
    # Access
    # ------------------------------------------------------------------

    def get(self, name: str) -> IDEExtension | None:
        """Restituisce un'estensione tramite nome."""
        for extension in self.extensions:
            if extension.name == name:
                return extension

        return None

    def all(self) -> list[IDEExtension]:
        """Restituisce tutte le estensioni caricate."""
        return list(self.extensions)

    def errors_all(self) -> dict[str, str]:
        """Restituisce gli errori dell'ultimo caricamento."""
        return dict(self.errors)

    def clear(self) -> None:
        """Svuota il registro delle estensioni e degli errori."""
        self.extensions.clear()
        self.errors.clear()

    def __len__(self) -> int:
        return len(self.extensions)

    def __iter__(self):
        return iter(self.extensions)
