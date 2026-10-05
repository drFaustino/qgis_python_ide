from __future__ import annotations

import ast
import builtins
import importlib
import inspect
import re
import threading
import pkgutil
import sys
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Symbol:
    name: str
    kind: str
    type_name: str = "Any"
    doc: str = ""
    signature: str = ""
    module: str = ""


@dataclass
class TypeInfo:
    name: str
    members: dict[str, Symbol] = field(default_factory=dict)
    doc: str = ""


class PyQGISLanguageService:
    """
    Language service PyQGIS leggero, eseguito direttamente nell'ambiente
    Python di QGIS.

    L'indicizzazione viene eseguita solo quando necessaria e viene mantenuta
    in memoria per evitare rallentamenti all'avvio dell'IDE.
    """

    ROOT_MODULES = (
        "qgis",
        "qgis.core",
        "qgis.gui",
        "qgis.analysis",
        "qgis.processing",
        "qgis.PyQt",
        "qgis.PyQt.QtCore",
        "qgis.PyQt.QtGui",
        "qgis.PyQt.QtWidgets",
        "qgis.PyQt.uic",
    )

    COMMON_TYPES = {
        "iface": "QgisInterface",
        "QgsProject.instance()": "QgsProject",
        "iface.activeLayer()": "QgsMapLayer",
        "feature.geometry()": "QgsGeometry",
        "feature": "QgsFeature",
        "layer": "QgsMapLayer",
        "project": "QgsProject",
        "geom": "QgsGeometry",
        "geometry": "QgsGeometry",
        "request": "QgsFeatureRequest",
    }

    PYTHON_BUILTINS = (
        "abs", "all", "any", "bool", "bytes", "callable", "dict",
        "enumerate", "filter", "float", "format", "frozenset", "getattr",
        "hasattr", "hash", "help", "id", "int", "isinstance", "issubclass",
        "iter", "len", "list", "map", "max", "min", "next", "open",
        "print", "property", "range", "repr", "reversed", "round",
        "set", "setattr", "slice", "sorted", "str", "sum", "super",
        "tuple", "type", "vars", "zip", "Exception", "RuntimeError",
        "ValueError", "TypeError", "KeyError", "IndexError", "object",
    )

    FALLBACK_SYMBOLS = {
        "QgsProject": "qgis.core",
        "QgsMapLayer": "qgis.core",
        "QgsVectorLayer": "qgis.core",
        "QgsRasterLayer": "qgis.core",
        "QgsFeature": "qgis.core",
        "QgsGeometry": "qgis.core",
        "QgsFeatureRequest": "qgis.core",
        "QgsMessageLog": "qgis.core",
        "QgsTask": "qgis.core",
        "QgsApplication": "qgis.core",
        "QgsProcessing": "qgis.core",
        "QgsProcessingFeedback": "qgis.core",
        "Qgis": "qgis.core",
        "QgsWkbTypes": "qgis.core",
        "QgsField": "qgis.core",
        "QgsFields": "qgis.core",
        "QgsCoordinateReferenceSystem": "qgis.core",
        "QgsCoordinateTransform": "qgis.core",
        "QgsDistanceArea": "qgis.core",
        "QgsSpatialIndex": "qgis.core",
        "QgsExpression": "qgis.core",
        "QgsExpressionContext": "qgis.core",
        "QgsSymbol": "qgis.core",
        "QgsRendererCategory": "qgis.core",
        "QgsSingleSymbolRenderer": "qgis.core",
        "QgsMapCanvas": "qgis.gui",
        "QgsMapTool": "qgis.gui",
        "QgisInterface": "qgis.gui",
    }

    def __init__(self):
        self.symbols: dict[str, Symbol] = {}
        self.types: dict[str, TypeInfo] = {}

        self._ready = False
        self._lock = threading.RLock()
        self._installed_modules: list[str] | None = None
        self._module_members_cache: dict[str, list[Symbol]] = {}

        self._load_builtin_fallbacks()
        self._load_python_builtins()

    # ------------------------------------------------------------------
    # Inizializzazione
    # ------------------------------------------------------------------

    def _load_python_builtins(self) -> None:
        """Indicizza i simboli Python più comuni per il completamento globale."""
        for name in self.PYTHON_BUILTINS:
            obj = getattr(builtins, name, None)
            if obj is None:
                continue
            kind = "class" if inspect.isclass(obj) else "function"
            self.symbols.setdefault(
                name,
                Symbol(
                    name=name,
                    kind=kind,
                    type_name=getattr(obj, "__name__", "Any"),
                    doc=self._safe_doc(obj),
                    signature=self._safe_signature(obj) if callable(obj) else "",
                    module="builtins",
                ),
            )

    def _load_builtin_fallbacks(self) -> None:
        for name, module in self.FALLBACK_SYMBOLS.items():
            self.symbols.setdefault(
                name,
                Symbol(
                    name=name,
                    kind="class",
                    type_name=name,
                    module=module,
                ),
            )

    def reset_index(self) -> None:
        """Svuota l'indice runtime mantenendo i fallback."""
        self.reset()

    def ensure_indexed(self) -> None:
        """
        Costruisce l'indice PyQGIS una sola volta.

        Gli oggetti SIP di QGIS non espongono sempre una signature
        compatibile con inspect.signature(), quindi ogni introspezione
        potenzialmente problematica viene isolata.
        """
        with self._lock:
            if self._ready:
                return

            for module_name in self.ROOT_MODULES:
                self._index_module(module_name)

            self._index_iface()

            self._ready = True

    def _index_module(self, module_name: str) -> None:
        try:
            module = importlib.import_module(module_name)
        except Exception:
            return

        try:
            names = dir(module)
        except Exception:
            return

        for name in names:
            if not name or name.startswith("_"):
                continue

            try:
                obj = getattr(module, name)
            except Exception:
                continue

            if inspect.isclass(obj):
                self._index_class(name, obj, module_name)
                continue

            if callable(obj):
                doc = self._safe_doc(obj)
                self.symbols.setdefault(
                    name,
                    Symbol(
                        name=name,
                        kind="function",
                        type_name="Any",
                        doc=doc,
                        module=module_name,
                    ),
                )

    def _index_class(
        self,
        name: str,
        obj: Any,
        module_name: str,
    ) -> None:
        doc = self._safe_doc(obj)
        signature = self._safe_signature(obj)

        self.symbols.setdefault(
            name,
            Symbol(
                name=name,
                kind="class",
                type_name=name,
                doc=doc,
                signature=signature,
                module=module_name,
            ),
        )

        self._index_type(name, obj, module_name)

    def _index_iface(self) -> None:
        try:
            from qgis.utils import iface
        except Exception:
            return

        if iface is None:
            return

        try:
            cls = iface.__class__
        except Exception:
            return

        self._index_type(
            "QgisInterface",
            cls,
            "qgis.gui",
        )

        self.symbols["iface"] = Symbol(
            name="iface",
            kind="object",
            type_name="QgisInterface",
            doc=self._safe_doc(cls),
            module="qgis.utils",
        )


    def _installed_module_names(self) -> list[str]:
        """Restituisce i moduli top-level installati nell'ambiente Python di QGIS."""
        if self._installed_modules is not None:
            return self._installed_modules
        names = set(sys_modules for sys_modules in ())
        try:
            names.update(name for _, name, _ in pkgutil.iter_modules())
        except Exception:
            names = set()
        names.update(sys.modules.keys())
        self._installed_modules = sorted(
            name for name in names
            if re.match(r"^[A-Za-z_]\w*$", name)
        )
        return self._installed_modules

    def _module_symbols(self, module_name: str) -> list[Symbol]:
        """Carica in modo sicuro i membri di un modulo per ``import X.`` e ``from X import``."""
        if module_name in self._module_members_cache:
            return self._module_members_cache[module_name]
        result: list[Symbol] = []
        try:
            module = importlib.import_module(module_name)
            for name in dir(module):
                if not name or name.startswith("_"):
                    continue
                try:
                    value = getattr(module, name)
                except Exception:
                    continue
                result.append(Symbol(
                    name=name,
                    kind="class" if inspect.isclass(value) else ("function" if callable(value) else "property"),
                    type_name=getattr(value, "__name__", "Any"),
                    doc=self._safe_doc(value),
                    signature=self._safe_signature(value) if callable(value) else "",
                    module=module_name,
                ))
        except Exception:
            result = []
        result.sort(key=lambda item: item.name.lower())
        self._module_members_cache[module_name] = result[:1000]
        return self._module_members_cache[module_name]

    def _import_completions(self, before: str) -> list[Symbol] | None:
        """Completa import, from-import e sottopacchetti come qgis.core/qgis.PyQt."""
        m = re.search(r"\bimport\s+([A-Za-z_][\w.]*)$", before)
        if m:
            prefix = m.group(1)
            if "." in prefix:
                module, fragment = prefix.rsplit(".", 1)
                candidates = []
                try:
                    parent = importlib.import_module(module)
                    for name in dir(parent):
                        if not name.startswith("_") and name.startswith(fragment):
                            candidates.append(Symbol(name=name, kind="module", module=module))
                    path = getattr(parent, "__path__", None)
                    if path:
                        candidates.extend(Symbol(name=name, kind="module", module=module) for _, name, _ in pkgutil.iter_modules(path) if name.startswith(fragment))
                except Exception:
                    candidates = []
                return candidates[:200]
            return [Symbol(name=name, kind="module", module="") for name in self._installed_module_names() if name.startswith(prefix)][:200]

        m = re.search(r"\bfrom\s+([A-Za-z_][\w.]*)\s+import\s*([A-Za-z_]\w*)?$", before)
        if m:
            module_name, prefix = m.group(1), (m.group(2) or "")
            return [item for item in self._module_symbols(module_name) if item.name.startswith(prefix)][:200]

        m = re.search(r"\bfrom\s+([A-Za-z_][\w.]*)(?:\.([A-Za-z_]\w*))?$", before)
        if m:
            module_name = m.group(1)
            trailing_fragment = m.group(2) or ""
            if trailing_fragment:
                parent_name = module_name
                prefix = trailing_fragment
            elif module_name.endswith("."):
                parent_name = module_name[:-1]
                prefix = ""
            else:
                parent_name = module_name.rsplit(".", 1)[0] if "." in module_name else None
                prefix = module_name.rsplit(".", 1)[-1]
            candidates: list[Symbol] = []
            try:
                if parent_name:
                    parent = importlib.import_module(parent_name)
                else:
                    parent = importlib.import_module(module_name)
                for name in dir(parent):
                    if not name.startswith("_") and name.startswith(prefix):
                        candidates.append(Symbol(name=name, kind="module", module=parent_name or ""))
                path = getattr(parent, "__path__", None)
                if path:
                    candidates.extend(Symbol(name=name, kind="module", module=parent_name or module_name) for _, name, _ in pkgutil.iter_modules(path) if name.startswith(prefix))
            except Exception:
                pass_items = []
                del pass_items
            return candidates[:200]
        return None

    # ------------------------------------------------------------------
    # Introspezione
    # ------------------------------------------------------------------

    @staticmethod
    def _safe_doc(obj: Any) -> str:
        try:
            return inspect.getdoc(obj) or ""
        except Exception:
            return ""

    @staticmethod
    def _safe_signature(obj: Any) -> str:
        try:
            return str(inspect.signature(obj))
        except Exception:
            return ""

    def _index_type(
        self,
        name: str,
        obj: Any,
        module: str,
    ) -> None:
        type_info = self.types.setdefault(
            name,
            TypeInfo(
                name=name,
                doc=self._safe_doc(obj),
            ),
        )

        try:
            members = dir(obj)
        except Exception:
            return

        for member_name in members:
            if not member_name or member_name.startswith("_"):
                continue

            try:
                value = getattr(obj, member_name)
            except Exception:
                continue

            kind = "method" if callable(value) else "property"
            type_name = "Any"

            if isinstance(value, type):
                type_name = getattr(
                    value,
                    "__name__",
                    "Any",
                )

            signature = ""
            if callable(value):
                signature = self._safe_signature(value)

            symbol = Symbol(
                name=member_name,
                kind=kind,
                type_name=type_name,
                doc=self._safe_doc(value),
                signature=signature,
                module=module,
            )

            type_info.members.setdefault(
                member_name,
                symbol,
            )

    # ------------------------------------------------------------------
    # Inferenza dei tipi
    # ------------------------------------------------------------------

    def resolve_type(
        self,
        expression: str,
        source: str = "",
    ) -> str | None:
        expression = expression.strip()

        if not expression:
            return None

        if expression in self.COMMON_TYPES:
            return self.COMMON_TYPES[expression]

        if expression.endswith(".geometry()"):
            return "QgsGeometry"

        if (
            expression.endswith(".activeLayer()")
            and "iface" in expression
        ):
            return "QgsMapLayer"

        if (
            expression.endswith(".instance()")
            and expression.startswith("QgsProject")
        ):
            return "QgsProject"

        root_name = expression.split(".", 1)[0]

        if (
            root_name.startswith("Qgs")
            and root_name in self.symbols
        ):
            return root_name

        return None

    def infer_source(
        self,
        source: str,
    ) -> dict[str, str]:
        result = {
            "iface": "QgisInterface",
        }

        try:
            tree = ast.parse(source)
        except (SyntaxError, ValueError, TypeError):
            return result

        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                type_name = self._infer_assignment_type(
                    node.value,
                    source,
                )

                if type_name:
                    self._assign_type_to_targets(
                        node.targets,
                        type_name,
                        result,
                    )

            elif isinstance(node, ast.AnnAssign):
                if isinstance(node.target, ast.Name):
                    annotation = self._annotation_name(
                        node.annotation
                    )

                    if annotation:
                        result[node.target.id] = annotation

            elif isinstance(node, ast.For):
                if self._is_get_features_call(node.iter):
                    if isinstance(node.target, ast.Name):
                        result[node.target.id] = "QgsFeature"

        return result

    def _infer_assignment_type(
        self,
        value: ast.AST,
        source: str,
    ) -> str | None:
        expression = self._unparse(value)

        if expression:
            resolved = self.resolve_type(
                expression,
                source,
            )

            if resolved:
                return resolved

        if not isinstance(value, ast.Call):
            return None

        if isinstance(value.func, ast.Attribute):
            base = self._unparse(value.func.value)
            attribute = value.func.attr

            if attribute == "geometry":
                return "QgsGeometry"

            if attribute == "activeLayer":
                return "QgsMapLayer"

            if attribute == "getFeatures":
                return "QgsFeatureIterator"

            if (
                attribute == "instance"
                and base == "QgsProject"
            ):
                return "QgsProject"

        if isinstance(value.func, ast.Name):
            function_name = value.func.id

            if function_name in self.symbols:
                symbol = self.symbols[function_name]

                if symbol.kind == "class":
                    return symbol.type_name

        return None

    @staticmethod
    def _assign_type_to_targets(
        targets: list[ast.expr],
        type_name: str,
        result: dict[str, str],
    ) -> None:
        for target in targets:
            if isinstance(target, ast.Name):
                result[target.id] = type_name

    @staticmethod
    def _annotation_name(annotation: ast.AST) -> str | None:
        if isinstance(annotation, ast.Name):
            return annotation.id

        if isinstance(annotation, ast.Attribute):
            return annotation.attr

        if isinstance(annotation, ast.Subscript):
            if isinstance(annotation.value, ast.Name):
                return annotation.value.id

        return None

    @staticmethod
    def _is_get_features_call(node: ast.AST) -> bool:
        return (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "getFeatures"
        )

    @staticmethod
    def _unparse(node: ast.AST) -> str:
        try:
            return ast.unparse(node)
        except (AttributeError, TypeError):
            return ""

    @staticmethod
    def _parse_for_completion(source: str, line: int | None = None) -> ast.AST | None:
        """Parsa anche un documento temporaneamente incompleto durante la digitazione."""
        try:
            return ast.parse(source)
        except (SyntaxError, ValueError, TypeError):
            if line is None:
                return None
        lines = source.splitlines()
        if not 1 <= line <= len(lines):
            return None
        current = lines[line - 1]
        indent = current[: len(current) - len(current.lstrip())]
        lines[line - 1] = indent + "..."
        try:
            return ast.parse("\n".join(lines))
        except (SyntaxError, ValueError, TypeError):
            return None

    @classmethod
    def _enclosing_class_name(cls, source: str, line: int) -> str | None:
        tree = cls._parse_for_completion(source, line)
        if tree is None:
            return None
        best = None
        best_depth = -1
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            end = getattr(node, "end_lineno", node.lineno)
            if node.lineno <= line <= end and node.lineno > best_depth:
                best = node.name
                best_depth = node.lineno
        return best

    def _index_source_context(self, source: str, line: int | None = None) -> dict[str, str]:
        """Indicizza classi/funzioni/import del documento corrente.

        Serve anche a rendere utile ``self.`` dentro le classi definite
        dall'utente, senza modificare l'indice globale delle API QGIS.
        """
        local_types = self.infer_source(source)
        tree = self._parse_for_completion(source, line)
        if tree is None:
            return local_types

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    local_types[alias.asname or alias.name.split(".")[0]] = alias.name
            elif isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    if alias.name != "*":
                        local_types[alias.asname or alias.name] = alias.name
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self.symbols.setdefault(
                    node.name,
                    Symbol(name=node.name, kind="function", type_name="Callable",
                           doc=ast.get_docstring(node) or "", module="__main__"),
                )
            elif isinstance(node, ast.ClassDef):
                self._index_source_class(node)

        return local_types

    def _index_source_class(self, node: ast.ClassDef) -> None:
        """Costruisce un TypeInfo locale per la classe corrente."""
        info = TypeInfo(name=node.name, doc=ast.get_docstring(node) or "")
        for base in node.bases:
            base_name = self._annotation_name(base)
            if base_name and base_name in self.types:
                info.members.update(self.types[base_name].members)
        for child in node.body:
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                args = child.args.args
                signature = self._source_signature(child)
                info.members[child.name] = Symbol(
                    name=child.name, kind="method", type_name="Callable",
                    doc=ast.get_docstring(child) or "", signature=signature,
                    module="__main__",
                )
                if args and args[0].arg == "self":
                    continue
            elif isinstance(child, ast.Assign):
                for target in child.targets:
                    if isinstance(target, ast.Name):
                        info.members[target.id] = Symbol(
                            name=target.id, kind="property", type_name="Any", module="__main__"
                        )
            elif isinstance(child, ast.AnnAssign) and isinstance(child.target, ast.Name):
                info.members[child.target.id] = Symbol(
                    name=child.target.id, kind="property",
                    type_name=self._annotation_name(child.annotation) or "Any", module="__main__"
                )
        self.types[node.name] = info
        self.symbols.setdefault(
            node.name,
            Symbol(name=node.name, kind="class", type_name=node.name,
                   doc=info.doc, module="__main__"),
        )

    @staticmethod
    def _source_signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
        args = []
        positional = list(node.args.posonlyargs) + list(node.args.args)
        defaults = [None] * (len(positional) - len(node.args.defaults)) + list(node.args.defaults)
        for arg, default in zip(positional, defaults):
            text = arg.arg
            if default is not None:
                try:
                    text += "=" + ast.unparse(default)
                except (AttributeError, TypeError):
                    text += "=…"
            args.append(text)
        if node.args.vararg:
            args.append("*" + node.args.vararg.arg)
        if node.args.kwarg:
            args.append("**" + node.args.kwarg.arg)
        return f"({', '.join(args)})"

    # ------------------------------------------------------------------
    # Completamento
    # ------------------------------------------------------------------

    def completions(
        self,
        source: str,
        line: int,
        column: int,
    ) -> list[Symbol]:
        self.ensure_indexed()

        with self._lock:
            return self._completions_locked(source, line, column)

    def _completions_locked(self, source: str, line: int, column: int) -> list[Symbol]:
        lines = source.splitlines()
        local_types = self._index_source_context(source, line)

        if 0 < line <= len(lines):
            current_line = lines[line - 1]
        else:
            current_line = ""

        column = max(0, min(column, len(current_line)))
        before = current_line[:column]

        import_items = self._import_completions(before)
        if import_items is not None:
            return sorted(import_items, key=lambda item: item.name.lower())[:200]

        enclosing_class = self._enclosing_class_name(source, line)
        if enclosing_class:
            local_types.setdefault("self", enclosing_class)

        if re.search(r"\bqgis\.[A-Za-z_]*$", before):
            fragment = re.search(r"\bqgis\.([A-Za-z_]\w*)?$", before)
            prefix = fragment.group(1) if fragment and fragment.group(1) else ""
            candidates = []
            try:
                import qgis
                candidates.extend(
                    Symbol(name=name, kind="module", module="qgis")
                    for name in dir(qgis)
                    if not name.startswith("_") and name.startswith(prefix)
                )
                if getattr(qgis, "__path__", None):
                    candidates.extend(
                        Symbol(name=name, kind="module", module="qgis")
                        for _, name, _ in pkgutil.iter_modules(qgis.__path__)
                        if name.startswith(prefix)
                    )
            except Exception:
                candidates = []
            unique = {item.name: item for item in candidates}
            return sorted(unique.values(), key=lambda item: item.name.lower())[:200]

        member_match = re.search(
            r"([A-Za-z_]\w*)\.([A-Za-z_]\w*)?$",
            before,
        )

        if member_match:
            base = member_match.group(1)
            prefix = member_match.group(2) or ""

            type_name = (
                local_types.get(base)
                or self.resolve_type(base, source)
            )

            if type_name and type_name in self.types:
                members = self.types[type_name].members

                return sorted(
                    (
                        symbol
                        for name, symbol in members.items()
                        if name.startswith(prefix)
                    ),
                    key=lambda symbol: symbol.name,
                )[:200]

        prefix_match = re.search(
            r"[A-Za-z_]\w*$",
            before,
        )
        prefix = (
            prefix_match.group(0)
            if prefix_match
            else ""
        )

        values = list(self.symbols.values())

        values.extend(
            Symbol(
                name=name,
                kind="variable",
                type_name=type_name,
            )
            for name, type_name in local_types.items()
        )

        seen: set[str] = set()
        result: list[Symbol] = []

        for symbol in values:
            if not symbol.name.startswith(prefix):
                continue

            if symbol.name in seen:
                continue

            seen.add(symbol.name)
            result.append(symbol)

        return sorted(
            result,
            key=lambda symbol: (
                0 if symbol.name.startswith(prefix) else 1,
                symbol.name.lower(),
            ),
        )[:200]

    # ------------------------------------------------------------------
    # Documentazione
    # ------------------------------------------------------------------

    def documentation(
        self,
        expression: str,
        source: str = "",
    ) -> Symbol | None:
        self.ensure_indexed()

        with self._lock:
            return self._documentation_locked(expression, source)

    def _documentation_locked(self, expression: str, source: str = "") -> Symbol | None:
        expression = expression.strip()

        if not expression:
            return None

        if "." not in expression:
            return self.symbols.get(expression)

        base, member = expression.rsplit(".", 1)

        local_types = self.infer_source(source)

        type_name = (
            local_types.get(base)
            or self.resolve_type(base, source)
        )

        if not type_name:
            return None

        type_info = self.types.get(type_name)

        if type_info is None:
            return None

        return type_info.members.get(member)

    # ------------------------------------------------------------------
    # Utility pubbliche
    # ------------------------------------------------------------------

    def is_ready(self) -> bool:
        return self._ready

    def reset(self) -> None:
        """
        Cancella l'indice generato e mantiene i fallback di base.
        """
        with self._lock:
            self.symbols.clear()
            self.types.clear()
            self._ready = False
            self._load_builtin_fallbacks()
