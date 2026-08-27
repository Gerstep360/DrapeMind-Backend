import json
import re
from typing import Any


MEMORY_MARKER = "AI_MEMORY_JSON="


def load_ai_memory(summary: str | None) -> dict[str, Any]:
    """Read compact, server-owned conversation memory from an AI session."""
    if not summary:
        return {}
    match = re.search(rf"{re.escape(MEMORY_MARKER)}(\{{.*\}})\s*$", summary, re.DOTALL)
    if not match:
        return {}
    try:
        value = json.loads(match.group(1))
    except (json.JSONDecodeError, TypeError):
        return {}
    return value if isinstance(value, dict) else {}


def merge_ai_memory(
    memory: dict[str, Any],
    updates: dict[str, Any] | None,
    recommended_product_ids: list[int],
) -> dict[str, Any]:
    """Merge only bounded, deterministic preferences and recent recommendations."""
    merged = dict(memory)
    for key, value in (updates or {}).items():
        if value not in (None, "", [], {}):
            merged[key] = value

    recent = [int(value) for value in merged.get("recommended_product_ids", []) if str(value).isdigit()]
    recent.extend(int(value) for value in recommended_product_ids if value)
    merged["recommended_product_ids"] = list(dict.fromkeys(recent))[-24:]
    return merged


def build_session_summary(conversation: str, memory: dict[str, Any]) -> str:
    payload = json.dumps(memory, ensure_ascii=False, separators=(",", ":"))
    return f"{conversation[:850]}\n{MEMORY_MARKER}{payload}"
