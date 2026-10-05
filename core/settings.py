from __future__ import annotations

from typing import Any

from qgis.PyQt.QtCore import QSettings


class IDESettings:
    """Gestione centralizzata delle impostazioni del QGIS Python IDE."""

    ORG = "QGIS"
    APP = "QGISPythonIDEPro"

    def __init__(self):
        self.s = QSettings(self.ORG, self.APP)

    def get(self, key: str, default: Any = None) -> Any:
        """Restituisce un'impostazione."""
        return self.s.value(key, default)

    def set(self, key: str, value: Any) -> None:
        """Salva un'impostazione."""
        self.s.setValue(key, value)

    def remove(self, key: str) -> None:
        """Rimuove un'impostazione."""
        self.s.remove(key)

    def contains(self, key: str) -> bool:
        """Verifica se un'impostazione esiste."""
        return self.s.contains(key)

    def geometry(self):
        """Restituisce la geometria salvata della finestra principale."""
        return self.s.value("geometry", None)

    def set_geometry(self, value) -> None:
        """Salva la geometria della finestra principale."""
        if value is not None:
            self.s.setValue("geometry", value)

    def clear_geometry(self) -> None:
        """Cancella la geometria salvata."""
        self.s.remove("geometry")

    def sync(self) -> None:
        """Forza la sincronizzazione delle impostazioni su disco."""
        self.s.sync()
