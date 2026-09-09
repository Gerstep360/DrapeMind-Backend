"""Streaming utilities. Only public answer text is exposed, never reasoning tokens."""
import json
import re


def partial_answer(raw: str) -> str:
    if not re.search(r'"type"\s*:\s*"finish"', raw):
        return ""
    match = re.search(r'"answer"\s*:\s*"((?:\\.|[^"\\])*)', raw, re.S)
    if not match:
        return ""
    text = match.group(1)
    # A network chunk may split an escape sequence. Wait for its next bytes.
    for trim in range(min(6, len(text)) + 1):
        candidate = text[:-trim] if trim else text
        try:
            return json.loads('"' + candidate + '"')
        except ValueError:
            continue
    return ""


def compact_observation(value, depth=0):
    if depth > 5:
        return "[detalle omitido]"
    if isinstance(value, list):
        return [compact_observation(item, depth + 1) for item in value[:5]]
    if isinstance(value, dict):
        return {key: compact_observation(item, depth + 1) for key, item in value.items()
                if key not in {"imagenes", "tags_ai", "descripcion_ai", "resumen_texto"}}
    if isinstance(value, str):
        return value[:350]
    return value
