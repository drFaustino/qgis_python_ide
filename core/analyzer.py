from __future__ import annotations

import ast
import builtins
import re
import shutil
import subprocess
from dataclasses import dataclass


@dataclass
class Diagnostic:
    line: int
    column: int
    severity: str
    message: str
    code: str = ""
    end_line: int = 0
    end_column: int = 0
    source: str = "builtin"
    fix: str = ""


class QGISPythonAnalyzer:
    """Analizzatore statico Python orientato allo sviluppo di plugin QGIS."""

    BUILTINS = set(dir(builtins))

    def analyze(
        self,
        source: str,
        filename: str = "<editor>",
        external: bool = True,
    ) -> list[Diagnostic]:
        diagnostics: list[Diagnostic] = []

        if not isinstance(source, str):
            source = str(source)

        try:
            tree = ast.parse(source, filename=filename)
        except SyntaxError as error:
            line = error.lineno or 1
            column = max(0, (error.offset or 1) - 1)

            diagnostics.append(
                Diagnostic(
                    line=line,
                    column=column,
                    severity="ERROR",
                    message=error.msg,
                    code="E999",
                    source="python",
                    end_line=line,
                    end_column=column + 1,
                )
            )
            return diagnostics

        diagnostics.extend(self._pass(tree))
        diagnostics.extend(self._common(tree))
        diagnostics.extend(self._imports(tree))
        diagnostics.extend(self._unreachable(tree))
        diagnostics.extend(self._shadowing(tree))
        diagnostics.extend(self._qgis_patterns(tree))
        diagnostics.extend(self._security(tree))

        if external:
            diagnostics.extend(self._external(source, filename))

        return sorted(
            diagnostics,
            key=lambda diagnostic: (
                diagnostic.line,
                diagnostic.column,
                self._severity_order(diagnostic.severity),
                diagnostic.code,
            ),
        )

    @staticmethod
    def _severity_order(severity: str) -> int:
        return {
            "ERROR": 0,
            "WARNING": 1,
            "INFO": 2,
        }.get(severity.upper(), 3)

    def _pass(self, tree: ast.AST) -> list[Diagnostic]:
        diagnostics: list[Diagnostic] = []

        for node in ast.walk(tree):
            if isinstance(node, ast.Pass):
                diagnostics.append(
                    Diagnostic(
                        line=node.lineno,
                        column=node.col_offset,
                        severity="WARNING",
                        message="pass rilevato: sostituiscilo con un'implementazione esplicita, una gestione dell'eccezione o un'eccezione NotImplementedError.",
                        code="QGIS001",
                        source="QGIS",
                        end_line=getattr(node, "end_lineno", node.lineno),
                        end_column=getattr(
                            node,
                            "end_col_offset",
                            node.col_offset + 4,
                        ),
                        fix=(
                            "Inserisci codice / Genera implementazione / "
                            "Elimina pass"
                        ),
                    )
                )

        return diagnostics

    def _common(self, tree: ast.AST) -> list[Diagnostic]:
        diagnostics: list[Diagnostic] = []

        for node in ast.walk(tree):
            if isinstance(node, ast.ExceptHandler) and node.type is None:
                diagnostics.append(
                    Diagnostic(
                        line=node.lineno,
                        column=node.col_offset,
                        severity="WARNING",
                        message=(
                            "except generico: valuta un'eccezione specifica."
                        ),
                        code="PY001",
                        source="builtin",
                        end_line=getattr(node, "end_lineno", node.lineno),
                        end_column=getattr(
                            node,
                            "end_col_offset",
                            node.col_offset + 1,
                        ),
                    )
                )

            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "print"
            ):
                diagnostics.append(
                    Diagnostic(
                        line=node.lineno,
                        column=node.col_offset,
                        severity="INFO",
                        message=(
                            "print() in un plugin QGIS: valuta "
                            "QgsMessageLog per il logging applicativo."
                        ),
                        code="QGIS002",
                        source="QGIS",
                    )
                )

            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "getFeatures"
            ):
                diagnostics.append(
                    Diagnostic(
                        line=node.lineno,
                        column=node.col_offset,
                        severity="INFO",
                        message=(
                            "Iterazione feature per feature: valuta filtri, "
                            "request e QgsTask per dataset grandi."
                        ),
                        code="QGIS003",
                        source="QGIS",
                    )
                )

        return diagnostics

    def _imports(self, tree: ast.AST) -> list[Diagnostic]:
        imported: list[tuple[str, ast.AST]] = []
        used: set[str] = set()

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    name = alias.asname or alias.name.split(".")[0]
                    imported.append((name, node))

            elif isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    if alias.name != "*":
                        name = alias.asname or alias.name
                        imported.append((name, node))

            elif isinstance(node, ast.Name):
                if isinstance(node.ctx, ast.Load):
                    used.add(node.id)

        diagnostics: list[Diagnostic] = []

        for name, node in imported:
            if name in used or name.startswith("_"):
                continue

            diagnostics.append(
                Diagnostic(
                    line=node.lineno,
                    column=node.col_offset,
                    severity="WARNING",
                    message=(
                        f"Import '{name}' apparentemente inutilizzato."
                    ),
                    code="F401",
                    source="builtin",
                    fix="Rimuovi import",
                )
            )

        return diagnostics

    def _unreachable(self, tree: ast.AST) -> list[Diagnostic]:
        diagnostics: list[Diagnostic] = []

        for node in ast.walk(tree):
            body = getattr(node, "body", None)

            if not isinstance(body, list):
                continue

            terminated = False

            for child in body:
                if terminated and hasattr(child, "lineno"):
                    diagnostics.append(
                        Diagnostic(
                            line=child.lineno,
                            column=child.col_offset,
                            severity="WARNING",
                            message="Codice potenzialmente irraggiungibile.",
                            code="PY002",
                            source="builtin",
                        )
                    )

                if isinstance(
                    child,
                    (
                        ast.Return,
                        ast.Raise,
                        ast.Break,
                        ast.Continue,
                    ),
                ):
                    terminated = True

        return diagnostics

    def _shadowing(self, tree: ast.AST) -> list[Diagnostic]:
        diagnostics: list[Diagnostic] = []

        for node in ast.walk(tree):
            if not isinstance(
                node,
                (
                    ast.FunctionDef,
                    ast.AsyncFunctionDef,
                    ast.ClassDef,
                ),
            ):
                continue

            if node.name not in self.BUILTINS:
                continue

            diagnostics.append(
                Diagnostic(
                    line=node.lineno,
                    column=node.col_offset,
                    severity="WARNING",
                    message=(
                        f"'{node.name}' nasconde un built-in Python."
                    ),
                    code="PY003",
                    source="builtin",
                )
            )

        return diagnostics

    def _qgis_patterns(self, tree: ast.AST) -> list[Diagnostic]:
        diagnostics: list[Diagnostic] = []

        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign):
                continue

            if not isinstance(node.value, ast.Call):
                continue

            if not isinstance(node.value.func, ast.Attribute):
                continue

            function = node.value.func

            if (
                isinstance(function.value, ast.Name)
                and function.value.id == "iface"
                and function.attr == "activeLayer"
            ):
                diagnostics.append(
                    Diagnostic(
                        line=node.lineno,
                        column=node.col_offset,
                        severity="INFO",
                        message=(
                            "Variabile derivata da iface.activeLayer(): "
                            "gestisci il caso layer=None prima di usarla."
                        ),
                        code="QGIS010",
                        source="QGIS",
                        fix="Aggiungi controllo layer",
                    )
                )

            if (
                isinstance(function.value, ast.Name)
                and function.value.id == "QgsProject"
                and function.attr == "instance"
            ):
                diagnostics.append(
                    Diagnostic(
                        line=node.lineno,
                        column=node.col_offset,
                        severity="INFO",
                        message=(
                            "Rilevato QgsProject.instance(): "
                            "completamento PyQGIS contestuale disponibile."
                        ),
                        code="QGIS011",
                        source="QGIS",
                    )
                )

        return diagnostics


    SECRET_KEYWORDS = (
        "password",
        "passwd",
        "pwd",
        "secret",
        "token",
        "api_key",
        "apikey",
        "private_key",
        "access_key",
        "client_secret",
    )

    def _security(self, tree: ast.AST) -> list[Diagnostic]:
        """Regole ispirate agli scanner del repository QGIS
        (https://plugins.qgis.org/docs/security-scanning):
        Bandit (Bxxx), detect-secrets (S1xx), Flake8 (F/E)."""
        diagnostics: list[Diagnostic] = []
        seen: set[tuple[int, str]] = set()

        def add(diagnostic: Diagnostic) -> None:
            key = (diagnostic.line, diagnostic.code)
            if key in seen:
                return
            seen.add(key)
            diagnostics.append(diagnostic)

        for node in ast.walk(tree):

            # --------------------------------------------------
            # assert  (Bandit B101)
            # --------------------------------------------------

            if isinstance(node, ast.Assert):
                add(
                    Diagnostic(
                        line=node.lineno,
                        column=node.col_offset,
                        severity="WARNING",
                        message=(
                            "assert rilevato (B101): viene rimosso con "
                            "'python -O'. Solleva un'eccezione esplicita."
                        ),
                        code="S101",
                        source="bandit",
                        fix=(
                            "Sostituisci con "
                            "'if not cond: raise ValueError(...)'"
                        ),
                        end_line=getattr(node, "end_lineno", node.lineno),
                        end_column=getattr(
                            node, "end_col_offset", node.col_offset + 6
                        ),
                    )
                )
                continue

            # --------------------------------------------------
            # except: pass  (Bandit B110)
            # --------------------------------------------------

            if isinstance(node, ast.ExceptHandler):
                if node.body and all(
                    isinstance(statement, ast.Pass)
                    for statement in node.body
                ):
                    add(
                        Diagnostic(
                            line=node.lineno,
                            column=node.col_offset,
                            severity="WARNING",
                            message=(
                                "except con pass (B110): eccezione "
                                "inghiottita silenziosamente. Usa "
                                "logging/QgsMessageLog o rilancia."
                            ),
                            code="S110",
                            source="bandit",
                            fix="Sostituisci pass con 'raise' o un log",
                            end_line=node.lineno,
                            end_column=node.col_offset + 6,
                        )
                    )

            # --------------------------------------------------
            # Confronti con None/True/False (Flake8 E711/E712)
            # --------------------------------------------------

            if isinstance(node, ast.Compare):
                for operator, comparator in zip(
                    node.ops, node.comparators
                ):
                    if not isinstance(comparator, ast.Constant):
                        continue
                    if isinstance(operator, ast.Eq) and (
                        comparator.value is None
                    ):
                        add(
                            Diagnostic(
                                line=node.lineno,
                                column=node.col_offset,
                                severity="INFO",
                                message=(
                                    "Confronto con '== None' (E711): "
                                    "usa 'is None'."
                                ),
                                code="E711",
                                source="flake8",
                                fix="Sostituisci '== None' con 'is None'",
                                end_line=node.lineno,
                                end_column=node.col_offset + 4,
                            )
                        )
                    if isinstance(operator, ast.NotEq) and (
                        comparator.value is None
                    ):
                        add(
                            Diagnostic(
                                line=node.lineno,
                                column=node.col_offset,
                                severity="INFO",
                                message=(
                                    "Confronto con '!= None' (E711): "
                                    "usa 'is not None'."
                                ),
                                code="E711",
                                source="flake8",
                                fix=(
                                    "Sostituisci '!= None' con "
                                    "'is not None'"
                                ),
                                end_line=node.lineno,
                                end_column=node.col_offset + 4,
                            )
                        )
                    if isinstance(
                        operator, (ast.Eq, ast.NotEq)
                    ) and comparator.value in (True, False):
                        add(
                            Diagnostic(
                                line=node.lineno,
                                column=node.col_offset,
                                severity="INFO",
                                message=(
                                    "Confronto con True/False (E712): "
                                    "usa 'is True/is False' o il valore "
                                    "direttamente."
                                ),
                                code="E712",
                                source="flake8",
                                fix=(
                                    "Sostituisci con 'is True/is False'"
                                ),
                                end_line=node.lineno,
                                end_column=node.col_offset + 4,
                            )
                        )

            # --------------------------------------------------
            # Assegnazioni: possibili segreti (detect-secrets S1xx)
            # --------------------------------------------------

            if isinstance(node, ast.Assign):
                assigned: list[str] = []

                for target in node.targets:
                    if isinstance(target, ast.Name):
                        assigned.append(target.id)
                    elif isinstance(target, ast.Attribute):
                        assigned.append(target.attr)
                    elif isinstance(target, (ast.Tuple, ast.List)):
                        assigned.extend(
                            element.id
                            for element in target.elts
                            if isinstance(element, ast.Name)
                        )

                is_secret_name = any(
                    keyword in variable.lower()
                    for variable in assigned
                    for keyword in self.SECRET_KEYWORDS
                )

                if (
                    is_secret_name
                    and isinstance(node.value, ast.Constant)
                    and isinstance(node.value.value, str)
                    and node.value.value.strip()
                ):
                    add(
                        Diagnostic(
                            line=node.lineno,
                            column=node.col_offset,
                            severity="ERROR",
                            message=(
                                "Possibile segreto hardcoded "
                                "(detect-secrets S105/S106): sposta il "
                                "valore in una variabile d'ambiente o "
                                "in QgsSettings."
                            ),
                            code="S105",
                            source="detect-secrets",
                            fix=(
                                "Usa os.environ.get(...) o QgsSettings"
                            ),
                            end_line=getattr(
                                node, "end_lineno", node.lineno
                            ),
                            end_column=getattr(
                                node, "end_col_offset", node.col_offset
                            ),
                        )
                    )

            # --------------------------------------------------
            # Chiamate (Bandit)
            # --------------------------------------------------

            if not isinstance(node, ast.Call):
                continue

            function = node.func

            qualified = ""
            if isinstance(function, ast.Name):
                qualified = function.id
            elif isinstance(function, ast.Attribute):
                qualified = function.attr
                if isinstance(function.value, ast.Name):
                    qualified = (
                        function.value.id + "." + function.attr
                    )

            simple = qualified.split(".")[-1]

            end_line = getattr(node, "end_lineno", node.lineno)
            end_column = getattr(
                node, "end_col_offset", node.col_offset
            )

            if qualified == "exec":
                add(
                    Diagnostic(
                        line=node.lineno,
                        column=node.col_offset,
                        severity="WARNING",
                        message=(
                            "exec() rilevato (B102): codice dinamico "
                            "pericoloso, evitalo se possibile."
                        ),
                        code="S102",
                        source="bandit",
                        fix="Rimuovi exec o aggiungi '# nosec'",
                        end_line=end_line,
                        end_column=end_column,
                    )
                )

            if qualified == "eval":
                add(
                    Diagnostic(
                        line=node.lineno,
                        column=node.col_offset,
                        severity="WARNING",
                        message=(
                            "eval() rilevato (B307): usa "
                            "ast.literal_eval per i letterali."
                        ),
                        code="S307",
                        source="bandit",
                        fix="Sostituisci con ast.literal_eval(...)",
                        end_line=end_line,
                        end_column=end_column,
                    )
                )

            if qualified in (
                "pickle.load",
                "pickle.loads",
            ):
                add(
                    Diagnostic(
                        line=node.lineno,
                        column=node.col_offset,
                        severity="WARNING",
                        message=(
                            "pickle.load(s) (B301): deserializzazione "
                            "non sicura di dati non attendibili."
                        ),
                        code="S301",
                        source="bandit",
                        fix="Preferisci json per dati non firmati",
                        end_line=end_line,
                        end_column=end_column,
                    )
                )

            if qualified == "tempfile.mktemp":
                add(
                    Diagnostic(
                        line=node.lineno,
                        column=node.col_offset,
                        severity="WARNING",
                        message=(
                            "tempfile.mktemp (B306): vulnerabile a race "
                            "condition. Usa tempfile.mkstemp()."
                        ),
                        code="S306",
                        source="bandit",
                        fix="Sostituisci con tempfile.mkstemp()",
                        end_line=end_line,
                        end_column=end_column,
                    )
                )

            if qualified in ("hashlib.md5", "hashlib.sha1"):
                add(
                    Diagnostic(
                        line=node.lineno,
                        column=node.col_offset,
                        severity="WARNING",
                        message=(
                            f"{qualified} (B324): hash crittograficamente "
                            "debole. Usa hashlib.sha256()."
                        ),
                        code="S324",
                        source="bandit",
                        fix="Sostituisci con hashlib.sha256()",
                        end_line=end_line,
                        end_column=end_column,
                    )
                )

            if qualified == "yaml.load":
                has_safe_loader = any(
                    keyword.arg == "Loader"
                    for keyword in node.keywords
                )
                if not has_safe_loader:
                    add(
                        Diagnostic(
                            line=node.lineno,
                            column=node.col_offset,
                            severity="WARNING",
                            message=(
                                "yaml.load senza Loader (B506): usa "
                                "yaml.safe_load()."
                            ),
                            code="S506",
                            source="bandit",
                            fix="Sostituisci con yaml.safe_load(...)",
                            end_line=end_line,
                            end_column=end_column,
                        )
                    )

            if qualified in ("os.system", "os.popen", "popen"):
                add(
                    Diagnostic(
                        line=node.lineno,
                        column=node.col_offset,
                        severity="WARNING",
                        message=(
                            f"{qualified} (B605/B606): usa "
                            "subprocess.run([...], capture_output=True) "
                            "senza shell."
                        ),
                        code="S602",
                        source="bandit",
                        fix=(
                            "Sostituisci con subprocess.run(lista, "
                            "capture_output=True)"
                        ),
                        end_line=end_line,
                        end_column=end_column,
                    )
                )

            if simple in (
                "run",
                "call",
                "check_call",
                "check_output",
                "Popen",
            ) and (
                qualified.startswith("subprocess.")
                or qualified == simple
            ):
                for keyword in node.keywords:
                    if (
                        keyword.arg == "shell"
                        and isinstance(keyword.value, ast.Constant)
                        and keyword.value.value is True
                    ):
                        add(
                            Diagnostic(
                                line=node.lineno,
                                column=node.col_offset,
                                severity="WARNING",
                                message=(
                                    "shell=True (B602): rischio di "
                                    "injection. Passa gli argomenti "
                                    "come lista con shell=False."
                                ),
                                code="S602",
                                source="bandit",
                                fix=(
                                    "Imposta shell=False e passa gli "
                                    "argomenti come lista"
                                ),
                                end_line=end_line,
                                end_column=end_column,
                            )
                        )

            if qualified in ("urlopen", "urllib.request.urlopen"):
                has_timeout = any(
                    keyword.arg == "timeout"
                    for keyword in node.keywords
                )
                if not has_timeout:
                    add(
                        Diagnostic(
                            line=node.lineno,
                            column=node.col_offset,
                            severity="WARNING",
                            message=(
                                "urlopen senza timeout (B310): la "
                                "chiamata puo' bloccare QGIS all'infinito."
                            ),
                            code="S310",
                            source="bandit",
                            fix="Aggiungi timeout=30 alla chiamata",
                            end_line=end_line,
                            end_column=end_column,
                        )
                    )

        # ------------------------------------------------------
        # Variabili assegnate mai lette (Flake8 F841)
        # ------------------------------------------------------

        for node in ast.walk(tree):
            if not isinstance(
                node, (ast.FunctionDef, ast.AsyncFunctionDef)
            ):
                continue

            local_loaded = {
                sub.id
                for sub in ast.walk(node)
                if isinstance(sub, ast.Name)
                and isinstance(sub.ctx, ast.Load)
            }

            for sub in ast.walk(node):
                if not isinstance(sub, ast.Name):
                    continue
                if not isinstance(sub.ctx, ast.Store):
                    continue
                if sub.id.startswith("_"):
                    continue
                if sub.id in local_loaded:
                    continue
                add(
                    Diagnostic(
                        line=sub.lineno,
                        column=sub.col_offset,
                        severity="INFO",
                        message=(
                            f"Variabile '{sub.id}' assegnata ma mai "
                            "letta (F841): rimuovila o rinominala "
                            "con prefisso '_'."
                        ),
                        code="F841",
                        source="flake8",
                        fix="Rinomina in _" + sub.id,
                        end_line=sub.lineno,
                        end_column=sub.col_offset + len(sub.id),
                    )
                )

        return diagnostics

    def _external(
        self,
        source: str,
        filename: str,
    ) -> list[Diagnostic]:
        if shutil.which("ruff"):
            return self._run_ruff(source, filename)

        if shutil.which("pyflakes"):
            return self._run_pyflakes(source)

        return []

    def _run_ruff(
        self,
        source: str,
        filename: str,
    ) -> list[Diagnostic]:
        # Percorso assoluto risolto via shutil.which: niente PATH
        # parziale né shell. Il codice analizzato arriva da stdin.
        executable = shutil.which("ruff")

        if not executable:
            return []

        try:
            process = subprocess.run(  # nosec B603 - eseguibile risolto con shutil.which, senza shell
                [
                    executable,
                    "check",
                    "--output-format",
                    "concise",
                    "--stdin-filename",
                    filename,
                    "-",
                ],
                input=source,
                text=True,
                capture_output=True,
                timeout=8,
                check=False,
            )
        except (
            OSError,
            subprocess.SubprocessError,
        ):
            return []

        output = process.stdout or process.stderr or ""
        return self._parse_external(output, "ruff")

    def _run_pyflakes(self, source: str) -> list[Diagnostic]:
        executable = shutil.which("pyflakes")

        if not executable:
            return []

        try:
            process = subprocess.run(  # nosec B603 - eseguibile risolto con shutil.which, senza shell
                [executable, "-"],
                input=source,
                text=True,
                capture_output=True,
                timeout=8,
                check=False,
            )
        except (
            OSError,
            subprocess.SubprocessError,
        ):
            return []

        output = process.stdout or process.stderr or ""
        return self._parse_external(output, "pyflakes")

    def _parse_external(
        self,
        text: str,
        source: str,
    ) -> list[Diagnostic]:
        diagnostics: list[Diagnostic] = []

        for line in text.splitlines():
            match = re.match(
                r"^.*?:(\d+):(\d+):\s*([A-Z]\d+)?\s*(.*)$",
                line,
            )

            if not match:
                continue

            line_number = int(match.group(1))
            column = max(0, int(match.group(2)) - 1)
            code = match.group(3) or source
            message = match.group(4).strip()

            diagnostics.append(
                Diagnostic(
                    line=line_number,
                    column=column,
                    severity="WARNING",
                    message=message,
                    code=code,
                    source=source,
                )
            )

        return diagnostics


def normalize_whitespace(source: str) -> str:
    """Normalizza spazi finali e righe vuote senza alterare l'indentazione."""

    if not isinstance(source, str):
        source = str(source)

    lines = (
        source
        .replace("\r\n", "\n")
        .replace("\r", "\n")
        .split("\n")
    )

    while lines and not lines[-1].strip():
        lines.pop()

    output: list[str] = []
    blank_lines = 0

    for line in lines:
        if not line.strip():
            blank_lines += 1

            if blank_lines <= 2:
                output.append("")
        else:
            blank_lines = 0
            output.append(line.rstrip())

    if not output:
        return ""

    return "\n".join(output) + "\n"
