from __future__ import annotations

import json
from typing import Any


REASONING_REDACTION = (
    "[Reasoning resumido - ative AGNO_CONSOLE_STORE_REASONING=true para texto bruto]"
)


def consume_agno_event_buffer(buffer: str) -> tuple[list[dict[str, Any]], str]:
    """Extrai eventos Agno de NDJSON ou SSE, preservando partes incompletas."""
    text = buffer.replace("\r\n", "\n")
    events: list[dict[str, Any]] = []
    remainder = text

    while "\n\n" in remainder:
        frame, remainder = remainder.split("\n\n", 1)
        frame = frame.strip()
        if not frame:
            continue

        if looks_like_sse_frame(frame):
            event = parse_sse_frame(frame)
            if event:
                events.append(event)
            continue

        parsed, leftover = extract_json_objects(frame)
        events.extend(parsed)
        if leftover.strip():
            remainder = f"{leftover}{remainder}"
            break

    if looks_like_sse_frame(remainder):
        return events, remainder

    parsed, leftover = extract_json_objects(remainder)
    events.extend(parsed)
    return events, leftover


def looks_like_sse_frame(text: str) -> bool:
    stripped = text.lstrip()
    return stripped.startswith("data:") or stripped.startswith("event:")


def parse_sse_frame(frame: str) -> dict[str, Any] | None:
    event_name = ""
    data_lines: list[str] = []

    for raw_line in frame.splitlines():
        line = raw_line.strip()
        if not line or line.startswith(":"):
            continue
        if line.startswith("event:"):
            event_name = line.removeprefix("event:").strip()
        elif line.startswith("data:"):
            data_lines.append(line.removeprefix("data:").strip())

    if not data_lines:
        return {"event": event_name} if event_name else None

    data_text = "\n".join(data_lines).strip()
    if not data_text or data_text == "[DONE]":
        return None

    try:
        payload = json.loads(data_text)
    except json.JSONDecodeError:
        payload = {"content": data_text}

    if not isinstance(payload, dict):
        payload = {"content": payload}

    if event_name and not payload.get("event"):
        payload["event"] = event_name
    return payload


def extract_json_objects(text: str) -> tuple[list[dict[str, Any]], str]:
    events: list[dict[str, Any]] = []
    cursor = 0

    while True:
        start = text.find("{", cursor)
        if start == -1:
            return events, ""

        depth = 0
        in_string = False
        escaped = False
        end = -1

        for index in range(start, len(text)):
            char = text[index]
            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
            elif char == '"':
                in_string = True
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    end = index
                    break

        if end == -1:
            return events, text[start:]

        raw = text[start : end + 1]
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            cursor = start + 1
            continue

        if isinstance(payload, dict):
            events.append(payload)
        cursor = end + 1


def sanitize_agno_event_for_console(
    event: dict[str, Any],
    *,
    store_full_reasoning: bool = False,
) -> dict[str, Any]:
    event_name = str(event.get("event") or "")
    has_reasoning_payload = "reasoning" in event_name.lower() or "reasoning" in event
    if not has_reasoning_payload or store_full_reasoning:
        return event

    redacted = json.loads(json.dumps(event, ensure_ascii=False))

    def redact(value: Any) -> Any:
        if isinstance(value, dict):
            cleaned: dict[str, Any] = {}
            for key, item in value.items():
                lowered = str(key).lower()
                if lowered in {"content", "reasoning", "reasoning_content"}:
                    cleaned[key] = REASONING_REDACTION
                else:
                    cleaned[key] = redact(item)
            return cleaned
        if isinstance(value, list):
            return [redact(item) for item in value]
        return value

    return redact(redacted)
