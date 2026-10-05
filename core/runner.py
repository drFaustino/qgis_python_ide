from __future__ import annotations

import os
import sys
import tempfile
import traceback

from qgis.PyQt.QtCore import (
    QObject,
    pyqtSignal,
    QProcess,
    QProcessEnvironment,
)

from qgis.core import QgsPythonRunner


class ScriptRunner(QObject):
    """
    Gestisce l'esecuzione degli script dell'IDE.

    Modalità:

    - run_in_qgis():
        esecuzione nell'interprete Python già attivo di QGIS.

    - run_external():
        esecuzione in un processo Python separato, mantenendo però
        l'ambiente Python di QGIS quando disponibile.
    """

    output = pyqtSignal(str, str)
    finished = pyqtSignal(bool)

    def __init__(self, iface, parent=None):
        super().__init__(parent)

        self.iface = iface
        self.process = None
        self.running = False
        self._temporary_path = None

    # ------------------------------------------------------------------
    # Esecuzione dentro QGIS
    # ------------------------------------------------------------------

    def run_in_qgis(self, source, filename="<editor>"):
        """
        Esegue il codice nell'ambiente Python di QGIS.

        Se filename appartiene a un progetto plugin QGIS, viene
        inizializzato tramite classFactory(iface) e initGui().
        In caso contrario il codice viene eseguito normalmente.
        """
        if self.running:
            self.output.emit(
                "È già in corso un'esecuzione.",
                "WARNING",
            )
            return False

        source = "" if source is None else str(source)
        filename = str(filename or "<editor>")

        self.running = True

        try:
            plugin_root = self._find_plugin_root(filename)

            if plugin_root is not None:
                runner_code = self._build_plugin_qgis_code(
                    plugin_root,
                )

                self.output.emit(
                    f"Avvio plugin QGIS: {plugin_root}",
                    "INFO",
                )
            else:
                runner_code = self._build_qgis_code(
                    source,
                    filename,
                )

                self.output.emit(
                    f"Avvio script: {filename}",
                    "INFO",
                )

            ok = QgsPythonRunner.run(
                runner_code,
                "QGIS Python IDE",
            )

            ok = bool(ok)

            if ok:
                self.output.emit(
                    "Esecuzione completata in QGIS.",
                    "INFO",
                )
            else:
                self.output.emit(
                    "Esecuzione terminata con errore.",
                    "ERROR",
                )

            self.finished.emit(ok)

            return ok

        except Exception:
            self.output.emit(
                traceback.format_exc(),
                "ERROR",
            )

            self.finished.emit(False)

            return False

        finally:
            self.running = False

    def _build_qgis_code(self, source, filename):
        """
        Costruisce il codice eseguito da QgsPythonRunner.

        Gli import sono eseguiti direttamente nell'ambiente QGIS,
        invece di affidarsi a variabili globali già esistenti.
        """
        return (
            "from qgis.core import QgsProject\n"
            "from qgis.utils import iface\n"
            "from qgis.PyQt.QtCore import QCoreApplication\n"
            "\n"
            "exec(\n"
            "    compile(\n"
            f"        {source!r},\n"
            f"        {filename!r},\n"
            "        'exec'\n"
            "    ),\n"
            "    globals(),\n"
            "    globals()\n"
            ")\n"
        )

    def _find_plugin_root(self, filename):
        """
        Individua la directory radice di un plugin QGIS partendo
        dal file aperto nell'IDE.

        Un progetto viene considerato plugin quando contiene:
        - __init__.py
        - metadata.txt
        """
        if not filename:
            return None

        path = os.path.abspath(
            os.path.expanduser(str(filename))
        )

        if not os.path.isfile(path):
            return None

        current = os.path.dirname(path)

        while current:
            init_path = os.path.join(
                current,
                "__init__.py",
            )

            metadata_path = os.path.join(
                current,
                "metadata.txt",
            )

            if (
                os.path.isfile(init_path)
                and os.path.isfile(metadata_path)
            ):
                return current

            parent = os.path.dirname(current)

            if parent == current:
                break

            current = parent

        return None


    def _build_plugin_qgis_code(self, plugin_root):
        plugin_root = os.path.abspath(
            os.path.expanduser(str(plugin_root))
        )

        parent_directory = os.path.dirname(plugin_root)
        package_name = os.path.basename(plugin_root)

        return (
            "import importlib\n"
            "import os\n"
            "import sys\n"
            "import traceback\n"
            "from qgis import utils\n"
            "\n"
            f"plugin_root = {plugin_root!r}\n"
            f"parent_directory = {parent_directory!r}\n"
            f"package_name = {package_name!r}\n"
            "\n"
            "if not os.path.isdir(plugin_root):\n"
            "    raise RuntimeError(\n"
            "        f'Cartella plugin non trovata: {plugin_root}'\n"
            "    )\n"
            "\n"
            "metadata_path = os.path.join(\n"
            "    plugin_root,\n"
            "    'metadata.txt',\n"
            ")\n"
            "\n"
            "init_path = os.path.join(\n"
            "    plugin_root,\n"
            "    '__init__.py',\n"
            ")\n"
            "\n"
            "if not os.path.isfile(metadata_path):\n"
            "    raise RuntimeError(\n"
            "        f'metadata.txt non trovato: {metadata_path}'\n"
            "    )\n"
            "\n"
            "if not os.path.isfile(init_path):\n"
            "    raise RuntimeError(\n"
            "        f'__init__.py non trovato: {init_path}'\n"
            "    )\n"
            "\n"
            "if parent_directory not in sys.path:\n"
            "    sys.path.insert(0, parent_directory)\n"
            "\n"
            "importlib.invalidate_caches()\n"
            "\n"
            "old_plugin = utils.plugins.get(package_name)\n"
            "\n"
            "if old_plugin is not None:\n"
            "    old_unload = getattr(\n"
            "        old_plugin,\n"
            "        'unload',\n"
            "        None,\n"
            "    )\n"
            "\n"
            "    if callable(old_unload):\n"
            "        old_unload()\n"
            "\n"
            "    utils.plugins.pop(\n"
            "        package_name,\n"
            "        None,\n"
            "    )\n"
            "\n"
            "module = importlib.import_module(package_name)\n"
            "\n"
            "factory = getattr(\n"
            "    module,\n"
            "    'classFactory',\n"
            "    None,\n"
            ")\n"
            "\n"
            "if not callable(factory):\n"
            "    raise RuntimeError(\n"
            "        'Il plugin non espone una funzione '\n"
            "        'classFactory(iface).'\n"
            "    )\n"
            "\n"
            "plugin = factory(utils.iface)\n"
            "\n"
            "if plugin is None:\n"
            "    raise RuntimeError(\n"
            "        'classFactory(iface) non ha restituito '\n"
            "        'un plugin valido.'\n"
            "    )\n"
            "\n"
            "init_gui = getattr(\n"
            "    plugin,\n"
            "    'initGui',\n"
            "    None,\n"
            ")\n"
            "\n"
            "if not callable(init_gui):\n"
            "    raise RuntimeError(\n"
            "        'Il plugin non espone un metodo initGui().'\n"
            "    )\n"
            "\n"
            "try:\n"
            "    init_gui()\n"
            "except Exception:\n"
            "    utils.plugins.pop(\n"
            "        package_name,\n"
            "        None,\n"
            "    )\n"
            "    raise\n"
            "\n"
            "utils.plugins[package_name] = plugin\n"
            "\n"
            "print(\n"
            "    f'Plugin QGIS avviato correttamente: {package_name}',\n"
            "    flush=True,\n"
            ")\n"
        )

    # ------------------------------------------------------------------
    # Esecuzione esterna
    # ------------------------------------------------------------------

    def run_external(self, source, filename="<editor>"):
        """
        Esegue lo script in un processo separato.

        Il processo utilizza l'interprete Python corrente e riceve
        l'ambiente necessario per importare i moduli QGIS quando
        l'interprete corrente appartiene all'installazione QGIS.
        """
        if self._external_process_running():
            self.output.emit(
                "È già in corso un processo esterno.",
                "WARNING",
            )
            return False

        source = "" if source is None else str(source)
        filename = str(filename or "<editor>")

        fd = None
        path = None

        try:
            fd, path = tempfile.mkstemp(
                prefix="qgis_ide_",
                suffix=".py",
            )

            os.close(fd)
            fd = None

            with open(
                path,
                "w",
                encoding="utf-8",
                newline="",
            ) as handle:
                handle.write(source)

            self._temporary_path = path

            self.process = QProcess(self)

            environment = self._build_process_environment()

            if environment is not None:
                self.process.setProcessEnvironment(
                    environment
                )

            program = self._python_executable()

            self.process.setProgram(program)

            self.process.setArguments(
                [
                    path,
                ]
            )

            self.process.readyReadStandardOutput.connect(
                self._read_stdout
            )

            self.process.readyReadStandardError.connect(
                self._read_stderr
            )

            self.process.finished.connect(
                self._external_finished
            )

            self.process.errorOccurred.connect(
                self._process_error
            )

            self.running = True

            self.output.emit(
                f"Avvio processo esterno: {path}",
                "INFO",
            )

            self.output.emit(
                f"Interprete Python: {program}",
                "INFO",
            )

            self.process.start()

            if not self.process.waitForStarted(3000):
                self.output.emit(
                    "Impossibile avviare il processo Python esterno.",
                    "ERROR",
                )

                self._cleanup_process_file()

                self.running = False

                self.finished.emit(False)

                return False

            return True

        except Exception:
            if fd is not None:
                try:
                    os.close(fd)
                except OSError:
                    fd = None

            self.output.emit(
                traceback.format_exc(),
                "ERROR",
            )

            if path:
                self._remove_file(path)

            self._temporary_path = None
            self.running = False

            self.finished.emit(False)

            return False

    def _external_process_running(self):
        if self.process is None:
            return False

        try:
            return (
                self.process.state()
                != QProcess.ProcessState.NotRunning
            )
        except RuntimeError:
            return False

    def _python_executable(self):
        """
        Restituisce l'interprete Python da utilizzare.

        In QGIS viene preferito sys.executable, perché normalmente
        rappresenta l'ambiente Python associato all'installazione
        QGIS attualmente in esecuzione.
        """
        executable = sys.executable

        if executable and os.path.isfile(executable):
            return executable

        return "python"

    def _build_process_environment(self):
        """
        Costruisce l'ambiente del processo figlio.

        In particolare conserva sys.path nel PYTHONPATH, così che
        un processo avviato dall'IDE possa trovare i moduli caricati
        dall'ambiente QGIS.
        """
        try:
            environment = QProcessEnvironment.systemEnvironment()
        except Exception:
            return None

        python_paths = []

        existing_pythonpath = environment.value(
            "PYTHONPATH"
        )

        if existing_pythonpath:
            python_paths.extend(
                existing_pythonpath.split(
                    os.pathsep
                )
            )

        for path in sys.path:
            if not path:
                continue

            if path not in python_paths:
                python_paths.append(path)

        if python_paths:
            environment.insert(
                "PYTHONPATH",
                os.pathsep.join(python_paths),
            )

        # Conserviamo esplicitamente il percorso Python usato
        # dall'interprete corrente.
        pythonhome = os.environ.get("PYTHONHOME")

        if pythonhome:
            environment.insert(
                "PYTHONHOME",
                pythonhome,
            )

        # QGIS installa normalmente variabili utili al proprio
        # ambiente. Se esistono nel processo principale, vengono
        # ereditate automaticamente; qui assicuriamo solamente
        # PYTHONPATH.
        return environment

    # ------------------------------------------------------------------
    # Output processo esterno
    # ------------------------------------------------------------------

    def _read_stdout(self):
        self._read_channel(
            error=False
        )

    def _read_stderr(self):
        self._read_channel(
            error=True
        )

    def _read_channel(self, error):
        process = self.process

        if process is None:
            return

        try:
            if error:
                data = (
                    process.readAllStandardError()
                    .data()
                )
            else:
                data = (
                    process.readAllStandardOutput()
                    .data()
                )
        except RuntimeError:
            return

        if not data:
            return

        text = data.decode(
            "utf-8",
            "replace",
        ).rstrip()

        if not text:
            return

        self.output.emit(
            text,
            "ERROR" if error else "INFO",
        )

    def _process_error(self, error):
        """
        Gestisce gli errori di avvio di QProcess.
        """
        messages = {
            QProcess.ProcessError.FailedToStart:
                "Il processo Python non può essere avviato.",
            QProcess.ProcessError.Crashed:
                "Il processo Python è terminato in modo anomalo.",
            QProcess.ProcessError.Timedout:
                "Timeout durante l'operazione sul processo Python.",
            QProcess.ProcessError.WriteError:
                "Errore durante la scrittura sul processo Python.",
            QProcess.ProcessError.ReadError:
                "Errore durante la lettura dal processo Python.",
            QProcess.ProcessError.UnknownError:
                "Errore sconosciuto del processo Python.",
        }

        message = messages.get(
            error,
            "Errore nel processo Python esterno.",
        )

        self.output.emit(
            message,
            "ERROR",
        )

    # ------------------------------------------------------------------
    # Fine processo
    # ------------------------------------------------------------------

    def _external_finished(
        self,
        exit_code,
        exit_status,
    ):
        ok = (
            exit_code == 0
            and exit_status
            == QProcess.ExitStatus.NormalExit
        )

        self._read_stdout()
        self._read_stderr()

        path = self._temporary_path

        self._cleanup_process_file()

        self.running = False

        if ok:
            self.output.emit(
                f"Processo terminato (exit code {exit_code}).",
                "INFO",
            )
        else:
            self.output.emit(
                f"Processo terminato (exit code {exit_code}).",
                "ERROR",
            )

        self.finished.emit(ok)

        self.process = None

        if path:
            self._remove_file(path)

    # ------------------------------------------------------------------
    # Stop
    # ------------------------------------------------------------------

    def stop(self):
        """
        Interrompe un processo esterno.

        L'esecuzione interna a QGIS non viene terminata forzatamente,
        perché il codice è già dentro il processo principale di QGIS.
        """
        if not self._external_process_running():
            self.output.emit(
                "Nessun processo esterno in esecuzione.",
                "WARNING",
            )

            return False

        try:
            self.output.emit(
                "Interruzione processo richiesta.",
                "WARNING",
            )

            self.process.kill()

            return True

        except RuntimeError:
            self.output.emit(
                "Impossibile interrompere il processo esterno.",
                "ERROR",
            )

            return False

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def _cleanup_process_file(self):
        path = self._temporary_path
        self._temporary_path = None

        if path:
            self._remove_file(path)

    @staticmethod
    def _remove_file(path):
        try:
            if path and os.path.exists(path):
                os.remove(path)
        except OSError:
            return
