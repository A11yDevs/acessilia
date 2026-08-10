from __future__ import annotations

import re


def normalize_code_text(text: str) -> str:
    if not text:
        return ""

    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    # Docling costuma devolver código linearizado com TAB entre tokens.
    normalized = re.sub(r"\t+", " ", normalized)

    if _looks_flattened(normalized):
        normalized = _reflow_flat_code(normalized)

    return _cleanup_lines(normalized)


def _looks_flattened(text: str) -> bool:
    single_line = "\n" not in text
    long_line = max((len(line) for line in text.splitlines() or [text]), default=0) > 140
    javaish = any(token in text for token in (" class ", "public ", "private ", " if ", " else "))
    has_code_marks = any(token in text for token in ("{", "}", ";", "("))
    return (single_line or long_line) and javaish and has_code_marks


def _reflow_flat_code(text: str) -> str:
    lines: list[str] = []
    buf: list[str] = []
    brace_depth = 0
    paren_depth = 0
    in_string = False
    quote_char = ""
    escape = False

    def emit_current() -> None:
        content = "".join(buf).strip()
        if content:
            lines.append((" " * (brace_depth * 4)) + content)
        buf.clear()

    for ch in text:
        if in_string:
            buf.append(ch)
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == quote_char:
                in_string = False
            continue

        if ch in {'"', "'"}:
            in_string = True
            quote_char = ch
            buf.append(ch)
            continue

        if ch == "(":
            paren_depth += 1
            buf.append(ch)
            continue
        if ch == ")":
            paren_depth = max(0, paren_depth - 1)
            buf.append(ch)
            continue

        if ch == "{":
            buf.append(ch)
            emit_current()
            brace_depth += 1
            continue

        if ch == "}":
            emit_current()
            brace_depth = max(0, brace_depth - 1)
            lines.append((" " * (brace_depth * 4)) + "}")
            continue

        if ch == ";" and paren_depth == 0:
            buf.append(ch)
            emit_current()
            continue

        if ch == "\n":
            emit_current()
            continue

        buf.append(ch)

    emit_current()

    reflowed = "\n".join(lines)
    # Estilo Java frequente: "} else {".
    reflowed = re.sub(r"\n(\s*)else\s*\{", r"\n\1else {", reflowed)
    return reflowed


def _cleanup_lines(text: str) -> str:
    cleaned_lines: list[str] = []
    for line in text.splitlines():
        if not line.strip():
            if cleaned_lines and cleaned_lines[-1] != "":
                cleaned_lines.append("")
            continue
        # Preserva indentação inicial, mas normaliza espaçamento interno.
        leading = re.match(r"^\s*", line).group(0)
        body = line[len(leading):]
        body = re.sub(r"\s+", " ", body).strip()
        cleaned_lines.append(f"{leading}{body}".rstrip())

    while cleaned_lines and cleaned_lines[-1] == "":
        cleaned_lines.pop()
    return "\n".join(cleaned_lines)
