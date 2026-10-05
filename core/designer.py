from __future__ import annotations

import os
import shutil
import subprocess

from qgis.PyQt.QtWidgets import QMessageBox


def designer_executable() -> str | None:
    """
    Cerca un eseguibile Qt Designer disponibile nel PATH.
    """

    candidates = (
        "designer",
        "qt6-tools-designer",
        "pyside6-designer",
    )

    for executable in candidates:
        path = shutil.which(executable)

        if path:
            return path

    return None


def open_designer(
    parent,
    path: str | None = None,
) -> bool:
    """
    Avvia Qt Designer.

    Se 'path' è specificato, tenta di aprire direttamente quel file .ui.
    """

    executable = designer_executable()

    if not executable:
        QMessageBox.warning(
            parent,
            "Qt Designer",
            (
                "Qt Designer non è stato trovato nel PATH.\n\n"
                "Installa Qt Designer / PySide6 Designer "
                "e verifica che il relativo eseguibile "
                "sia disponibile nel PATH di QGIS."
            ),
        )
        return False

    arguments = [executable]

    if path:
        ui_path = os.path.abspath(
            os.path.expanduser(str(path))
        )

        if not os.path.isfile(ui_path):
            QMessageBox.warning(
                parent,
                "Qt Designer",
                f"Il file UI non esiste:\n{ui_path}",
            )
            return False

        arguments.append(ui_path)

    try:
        # L'eseguibile proviene dai rilevamenti pyuic6/pyside6 del
        # plugin (shutil.which) ed e' lanciato senza shell.
        subprocess.Popen(  # nosec B603 - eseguibile rilevato dal plugin, senza shell
            arguments,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
        )
        return True

    except OSError as error:
        QMessageBox.critical(
            parent,
            "Qt Designer",
            (
                "Impossibile avviare Qt Designer.\n\n"
                f"{error}"
            ),
        )
        return False

    except Exception as error:
        QMessageBox.critical(
            parent,
            "Qt Designer",
            str(error),
        )
        return False


def compile_ui(
    ui_path: str,
    py_path: str | None = None,
) -> str:
    """
    Compila un file Qt Designer .ui in Python.

    Restituisce il percorso del file Python generato.
    """

    ui_path = os.path.abspath(
        os.path.expanduser(str(ui_path))
    )

    if not os.path.isfile(ui_path):
        raise FileNotFoundError(
            f"File UI non trovato: {ui_path}"
        )

    if py_path is None:
        py_path = (
            os.path.splitext(ui_path)[0]
            + "_ui.py"
        )
    else:
        py_path = os.path.abspath(
            os.path.expanduser(str(py_path))
        )

    output_directory = os.path.dirname(py_path)

    if output_directory:
        os.makedirs(
            output_directory,
            exist_ok=True,
        )

    candidates = (
        "pyuic6",
        "pyside6-uic",
    )

    executable = None

    for candidate in candidates:
        path = shutil.which(candidate)

        if path:
            executable = path
            break

    if not executable:
        raise RuntimeError(
            "Nessun compilatore UI trovato nel PATH. "
            "Sono richiesti pyuic6 oppure pyside6-uic."
        )

    command = [
        executable,
        ui_path,
        "-o",
        py_path,
    ]

    try:
        # L'eseguibile proviene dai rilevamenti pyuic6/pyside6 del
        # plugin (shutil.which) ed e' lanciato senza shell.
        result = subprocess.run(  # nosec B603 - eseguibile rilevato dal plugin, senza shell
            command,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except OSError as error:
        raise RuntimeError(
            f"Impossibile avviare il compilatore UI: {error}"
        ) from error

    if result.returncode != 0:
        error_text = (
            result.stderr.strip()
            or result.stdout.strip()
            or "Errore sconosciuto durante la compilazione."
        )

        raise RuntimeError(
            "Compilazione del file .ui fallita:\n"
            + error_text
        )

    if not os.path.isfile(py_path):
        raise RuntimeError(
            "Il compilatore ha terminato senza errori, "
            "ma il file Python non è stato generato:\n"
            + py_path
        )

    return py_path
