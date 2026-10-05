from __future__ import annotations

import re
from pathlib import Path


OPTIONAL_FORMATTERS = {
    "isort": False,
    "autopep8": False,
    "black": False,
}


def _detect_optional_formatters():
    """Rileva i formatter opzionali senza generare errori."""
    detected = {}

    try:
        import isort  # noqa: F401
        detected["isort"] = True
    except ImportError:
        detected["isort"] = False

    try:
        import autopep8  # noqa: F401
        detected["autopep8"] = True
    except ImportError:
        detected["autopep8"] = False

    try:
        import black  # noqa: F401
        detected["black"] = True
    except ImportError:
        detected["black"] = False

    OPTIONAL_FORMATTERS.update(detected)


_detect_optional_formatters()


def formatter_status() -> dict[str, bool]:
    """
    Restituisce lo stato dei formatter opzionali.

    Esempio:
        {
            "isort": True,
            "autopep8": False,
            "black": True,
        }
    """
    return dict(OPTIONAL_FORMATTERS)


def format_document(text: str, suffix: str) -> str:
    """
    Formatta un documento in base all'estensione.

    Nessun formatter opzionale è obbligatorio.
    """
    text = "" if text is None else str(text)
    suffix = str(suffix or "").lower()

    if not suffix.startswith("."):
        suffix = "." + suffix

    if suffix in {".py", ".pyw"}:
        return _format_python(text)

    if suffix in {".qss", ".css"}:
        return _format_qss(text)

    if suffix in {".xml", ".ui", ".ts"}:
        return _format_xml(text)

    if suffix in {".md", ".markdown"}:
        return _format_markdown(text)

    if suffix in {".json"}:
        return _format_json(text)

    if suffix in {".yaml", ".yml"}:
        return _format_yaml(text)

    if suffix in {".txt", ".ini", ".cfg"}:
        return _format_text(text)

    return text


def trim_trailing(text: str) -> str:
    """
    Esegue l'equivalente di "Trim Trailing Whitespace" sull'intero documento.

    Vengono rimossi esclusivamente spazi e tab alla fine di ogni riga.
    Non vengono eliminate né accorpate righe vuote e non viene aggiunto un
    newline finale che non era presente nel documento.
    """
    text = "" if text is None else str(text)

    if not text:
        return ""

    # Mantiene esattamente i terminatori di riga presenti nel documento.
    lines = text.splitlines(keepends=True)
    output = []

    for line in lines:
        if line.endswith("\r\n"):
            body, ending = line[:-2], "\r\n"
        elif line.endswith("\n"):
            body, ending = line[:-1], "\n"
        elif line.endswith("\r"):
            body, ending = line[:-1], "\r"
        else:
            body, ending = line, ""

        output.append(body.rstrip(" \t") + ending)

    return "".join(output)


def _top_level_commas(body):
    """Indici delle virgole al livello piu' esterno del primo gruppo
    aperto della riga, ignorando stringhe e commenti."""
    stack = []
    commas = []
    quote = None
    index = 0
    total = len(body)

    while index < total:
        char = body[index]

        if quote is not None:
            if char == "\\":
                index += 2
                continue
            if body.startswith(quote, index):
                index += len(quote)
                quote = None
                continue
            index += 1
            continue

        if char in ("'", '"'):
            if body.startswith(char * 3, index):
                quote = char * 3
                index += 3
            else:
                quote = char
                index += 1
            continue

        if char == "#":
            break

        if char in "([{":
            stack.append(char)
        elif char in ")]}":
            if stack:
                stack.pop()
        elif char == "," and len(stack) == 1:
            commas.append(index)

        index += 1

    return commas


def _split_long_line(line, max_length):
    """Divide una riga lunga al livello delle virgole: un argomento per
    riga, stile PEP 8 con hanging indent di 4 spazi.
    Restituisce la lista delle nuove righe (o la riga originale)."""
    stripped = line.rstrip()

    if (
        len(stripped) <= max_length
        or "," not in stripped
        or not any(char in stripped for char in "([{")
    ):
        return [line]

    indent_length = len(line) - len(line.lstrip(" \t"))
    indent = line[:indent_length]
    body = line[indent_length:]

    commas = _top_level_commas(body)

    if not commas:
        return [line]

    open_index = None
    for index, char in enumerate(body):
        if char in "([{":
            open_index = index
            break

    if open_index is None:
        return [line]

    open_char = body[open_index]
    close_char = {"(": ")", "[": "]", "{": "}"}[open_char]

    tail = body.rstrip()
    suffix = ""
    if tail.endswith(close_char):
        group_end = len(tail) - 1
    elif tail.endswith(close_char + ":"):
        # Funzioni: def nome(...):  -> la ':' resta sulla riga di chiusura.
        group_end = len(tail) - 2
        suffix = ":"
    else:
        # Gruppo non chiuso a fine riga: non toccare.
        return [line]

    offset = open_index + 1
    inner = body[offset:group_end]

    chunks = []
    start = 0
    for position in commas:
        relative = position - offset
        chunks.append(inner[start:relative])
        start = relative + 1
    chunks.append(inner[start:])

    cleaned = [chunk.strip() for chunk in chunks]
    trailing_comma = False
    if cleaned and not cleaned[-1]:
        cleaned = cleaned[:-1]
        trailing_comma = True

    if len(cleaned) < 2:
        return [line]

    inner_indent = indent + "    "

    new_lines = [indent + body[:open_index + 1].rstrip()]
    for position, chunk in enumerate(cleaned):
        is_last = position == len(cleaned) - 1
        comma = "," if (not is_last or trailing_comma) else ""
        new_lines.append(inner_indent + chunk + comma)
    new_lines.append(indent + close_char + suffix)

    return new_lines


def _multiline_string_lines(text):
    """Numeri di riga (1-based) appartenenti a stringhe multiriga,
    da non toccare durante la riformattazione."""
    import io
    import tokenize

    protected = set()

    try:
        for token in tokenize.generate_tokens(
            io.StringIO(text).readline
        ):
            if (
                token.type == tokenize.STRING
                and token.end[0] > token.start[0]
            ):
                for number in range(
                    token.start[0], token.end[0] + 1
                ):
                    protected.add(number)
    except Exception:
        return set()

    return protected


def _split_long_lines(text, max_length=88):
    """Applica l'andata a capo dopo ogni virgola alle righe che superano
    la lunghezza massima (stile PEP 8 / documentazione Python)."""
    protected = _multiline_string_lines(text)
    output = []
    previous_continuation = False

    for number, line in enumerate(
        text.split("\n"), start=1
    ):
        bare = line.rstrip()

        if (
            number in protected
            or previous_continuation
            or bare.endswith("\\")
        ):
            output.append(line)
            previous_continuation = bare.endswith("\\")
            continue

        previous_continuation = False
        output.extend(
            _split_long_line(line, max_length)
        )

    return "\n".join(output)


def _ensure_final_newline(text):
    """Garantisce un singolo newline finale."""
    if not text.strip():
        return text
    return text.rstrip("\n") + "\n"


def _format_python(text: str) -> str:
    """
    Formatta Python utilizzando, nell'ordine:

        1. black (prioritaria: formattazione piu' corretta)
        2. autopep8
        3. isort + pulizia interna sicura

    I moduli opzionali non sono necessari per il funzionamento dell'IDE.
    """
    result = text

    # --------------------------------------------------------------
    # 1. black
    # --------------------------------------------------------------

    if OPTIONAL_FORMATTERS["black"]:
        formatted = _try_black(result)
        if formatted and formatted != result:
            return _safe_python_cleanup(formatted)

    # --------------------------------------------------------------
    # 2. autopep8
    # --------------------------------------------------------------

    if OPTIONAL_FORMATTERS["autopep8"]:
        try:
            import autopep8

            formatted = autopep8.fix_code(
                result,
                options={
                    "aggressive": 1,
                    "max_line_length": 88,
                },
            )
            if formatted and formatted != result:
                result = formatted
        except Exception:
            pass

    # --------------------------------------------------------------
    # 3. isort
    # --------------------------------------------------------------

    if OPTIONAL_FORMATTERS["isort"]:
        try:
            import isort

            result = isort.code(
                result,
                profile="black",
            )
        except Exception:
            pass

    # --------------------------------------------------------------
    # 4. riformattazione interna delle righe lunghe (andata a capo
    #    dopo ogni virgola, stile PEP 8) + pulizia finale.
    #    Applicata SEMPRE, anche dopo formatter esterni: e' idempotente
    #    e interviene solo su righe oltre la lunghezza massima.
    # --------------------------------------------------------------

    result = _split_long_lines(result)
    return _safe_python_cleanup(result)


def _try_black(text: str) -> str:
    """Applica Black se disponibile."""
    try:
        import black

        return black.format_str(
            text,
            mode=black.Mode(
                line_length=88,
            ),
        )

    except Exception:
        return text


def _safe_python_cleanup(text: str) -> str:
    """
    Pulizia finale sicura: trailing whitespace e newline finale.
    Per la riformattazione delle righe lunghe vedi _split_long_lines,
    sempre applicata da _format_python.
    """
    return _ensure_final_newline(trim_trailing(text))


def _format_qss(text: str) -> str:
    """
    Formattazione conservativa di QSS/CSS.
    """
    text = trim_trailing(text)

    if not text:
        return ""

    output = []
    depth = 0
    buffer = []

    in_string = None
    escaped = False
    in_comment = False

    index = 0

    while index < len(text):
        char = text[index]

        # ----------------------------------------------------------
        # Commenti /* ... */
        # ----------------------------------------------------------

        if in_comment:
            buffer.append(char)

            if char == "*" and index + 1 < len(text):
                if text[index + 1] == "/":
                    buffer.append("/")
                    index += 1
                    in_comment = False

            index += 1
            continue

        if (
            char == "/"
            and index + 1 < len(text)
            and text[index + 1] == "*"
        ):
            if buffer:
                buffer.append(char)
            else:
                buffer.append(char)

            buffer.append("*")
            index += 2
            in_comment = True
            continue

        # ----------------------------------------------------------
        # Stringhe
        # ----------------------------------------------------------

        if in_string is not None:
            buffer.append(char)

            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == in_string:
                in_string = None

            index += 1
            continue

        if char in {"'", '"'}:
            in_string = char
            buffer.append(char)
            index += 1
            continue

        # ----------------------------------------------------------
        # Apertura blocco
        # ----------------------------------------------------------

        if char == "{":
            content = "".join(buffer).strip()

            if content:
                output.append(
                    "    " * depth + content + " {"
                )

            buffer.clear()
            depth += 1

            index += 1
            continue

        # ----------------------------------------------------------
        # Chiusura blocco
        # ----------------------------------------------------------

        if char == "}":
            content = "".join(buffer).strip()

            if content:
                output.append(
                    "    " * depth + content
                )

            buffer.clear()

            depth = max(0, depth - 1)

            output.append(
                "    " * depth + "}"
            )

            index += 1
            continue

        # ----------------------------------------------------------
        # Fine dichiarazione
        # ----------------------------------------------------------

        if char == ";" and depth > 0:
            content = "".join(buffer).strip()

            if content:
                output.append(
                    "    " * depth + content + ";"
                )

            buffer.clear()

            index += 1
            continue

        # ----------------------------------------------------------
        # Nuova riga
        # ----------------------------------------------------------

        if char in {"\r", "\n"}:
            if buffer:
                buffer.append(" ")

            index += 1
            continue

        buffer.append(char)
        index += 1

    # --------------------------------------------------------------
    # Buffer finale
    # --------------------------------------------------------------

    content = "".join(buffer).strip()

    if content:
        output.append(
            "    " * depth + content
        )

    return "\n".join(output).rstrip() + "\n"


def _format_xml(text: str) -> str:
    """Formatta XML/UI usando la libreria standard Python."""
    text = "" if text is None else str(text)

    try:
        from xml.dom import minidom

        document = minidom.parseString(
            text.encode("utf-8")
        )

        result = document.toprettyxml(
            indent="  ",
            encoding="utf-8",
        )

        if isinstance(result, bytes):
            result = result.decode("utf-8")

        return trim_trailing(result)

    except Exception:
        return trim_trailing(text)


def _format_markdown(text: str) -> str:
    """Formatta Markdown in modo conservativo."""
    text = trim_trailing(text)

    if not text:
        return ""

    lines = text.splitlines()
    output = []

    for line in lines:
        # Titoli Markdown:
        # ##Titolo -> ## Titolo
        line = re.sub(
            r"^(#{1,6})(\S)",
            r"\1 \2",
            line,
        )

        # Liste:
        # *testo -> * testo
        # -testo -> - testo
        # +testo -> + testo
        line = re.sub(
            r"^(\s*[-*+])\s*",
            r"\1 ",
            line,
        )

        output.append(line.rstrip())

    return "\n".join(output) + "\n"


def _format_json(text: str) -> str:
    """Formatta JSON usando esclusivamente la libreria standard."""
    import json

    try:
        value = json.loads(text)

        return (
            json.dumps(
                value,
                indent=2,
                ensure_ascii=False,
            ).rstrip()
            + "\n"
        )

    except (ValueError, TypeError):
        return trim_trailing(text)


def _format_yaml(text: str) -> str:
    """
    YAML: usa PyYAML se disponibile.

    Se PyYAML non è installato, viene applicato solamente
    il cleanup degli spazi.
    """
    try:
        import yaml

        value = yaml.safe_load(text)

        if value is None:
            return ""

        result = yaml.safe_dump(
            value,
            allow_unicode=True,
            sort_keys=False,
            default_flow_style=False,
        )

        return trim_trailing(result)

    except ImportError:
        return trim_trailing(text)

    except Exception:
        return trim_trailing(text)


def _format_text(text: str) -> str:
    return trim_trailing(text)


def language_for_suffix(suffix: str) -> str:
    """
    Restituisce il linguaggio associato a un'estensione.
    """
    suffix = str(suffix or "").lower()

    if not suffix.startswith("."):
        suffix = "." + suffix

    return {
        ".py": "Python",
        ".pyw": "Python",
        ".md": "Markdown",
        ".markdown": "Markdown",
        ".qss": "QSS",
        ".css": "QSS",
        ".xml": "XML",
        ".ui": "XML",
        ".ts": "Qt TS",
        ".txt": "Text",
        ".ini": "INI",
        ".cfg": "INI",
        ".json": "JSON",
        ".yaml": "YAML",
        ".yml": "YAML",
    }.get(suffix, "Text")
