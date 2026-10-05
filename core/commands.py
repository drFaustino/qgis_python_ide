from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Any


@dataclass
class Command:
    """Comando registrato nell'IDE."""

    id: str
    title: str
    action: Callable[..., Any]
    category: str = "Generale"


class CommandRegistry:
    """Registro centrale dei comandi disponibili nell'IDE."""

    def __init__(self):
        self.commands: list[Command] = []

    def add(
        self,
        command_id: str,
        title: str,
        action: Callable[..., Any],
        category: str = "Generale",
    ) -> Command:
        """
        Registra un comando.

        Se esiste già un comando con lo stesso ID, viene sostituito.
        """
        command_id = str(command_id).strip()
        title = str(title).strip()
        category = str(category).strip() or "Generale"

        if not command_id:
            raise ValueError("L'ID del comando non può essere vuoto.")

        if not title:
            raise ValueError("Il titolo del comando non può essere vuoto.")

        if not callable(action):
            raise TypeError(
                f"L'azione del comando '{command_id}' deve essere callable."
            )

        command = Command(
            id=command_id,
            title=title,
            action=action,
            category=category,
        )

        for index, existing in enumerate(self.commands):
            if existing.id == command_id:
                self.commands[index] = command
                return command

        self.commands.append(command)
        return command

    def remove(self, command_id: str) -> bool:
        """Rimuove un comando tramite ID."""
        for index, command in enumerate(self.commands):
            if command.id == command_id:
                del self.commands[index]
                return True

        return False

    def get(self, command_id: str) -> Command | None:
        """Restituisce un comando tramite ID."""
        for command in self.commands:
            if command.id == command_id:
                return command

        return None

    def search(self, text: str = "") -> list[Command]:
        """
        Cerca i comandi per ID o titolo.

        La ricerca non distingue maiuscole/minuscole.
        """
        query = str(text).lower().strip()

        if not query:
            return list(self.commands)

        return [
            command
            for command in self.commands
            if (
                query in command.title.lower()
                or query in command.id.lower()
            )
        ]

    def clear(self) -> None:
        """Rimuove tutti i comandi registrati."""
        self.commands.clear()

    def all(self) -> list[Command]:
        """Restituisce una copia della lista dei comandi."""
        return list(self.commands)

    def __len__(self) -> int:
        return len(self.commands)
