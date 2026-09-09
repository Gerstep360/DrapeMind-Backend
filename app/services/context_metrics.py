"""LLM context metrics. Only counts/timings are logged, never prompt content."""
import json
import logging
from app.core.config import settings

logger = logging.getLogger("drapemind.ai.context")
_static_tokens = {}


async def context_metrics(client, messages, chat_id=None):
    parts = {"system": "", "tools": "", "state": "", "observations": "", "user": ""}
    if len(messages) >= 2 and messages[1].get("content", "").startswith("TOOLS:\n"):
        parts["system"] = messages[0]["content"]
        remaining = messages[1]["content"][len("TOOLS:\n"):]
        for key, delimiter in (("tools", "\nSTATE:\n"), ("state", "\nOBSERVATIONS:\n"),
                               ("observations", "\nUSER:\n")):
            parts[key], remaining = remaining.split(delimiter, 1)
        parts["user"] = remaining
    else:
        return None
    parts["continuation"] = "\n".join(item.get("content", "") for item in messages[2:])
    counts = {key: {"chars": len(value), "tokens": None} for key, value in parts.items()}
    if settings.AI_CONTEXT_TOKEN_METRICS:
        root = settings.AI_BASE_URL.rstrip("/").removesuffix("/v1")
        for key, value in parts.items():
            cache_key = (root, settings.AI_MODEL, key, value) if key in {"system", "tools"} else None
            if cache_key in _static_tokens:
                counts[key]["tokens"] = _static_tokens[cache_key]
                continue
            try:
                result = await client.post(root + "/tokenize", json={"content": value},
                                           headers={"Authorization": "Bearer " + settings.AI_API_KEY})
                result.raise_for_status()
                counts[key]["tokens"] = len(result.json()["tokens"])
                if cache_key:
                    if len(_static_tokens) >= 16:
                        _static_tokens.clear()
                    _static_tokens[cache_key] = counts[key]["tokens"]
            except Exception:
                # Tokenizer telemetry must never make an otherwise valid inference fail.
                pass
    try:
        state = json.loads(parts["state"])
        entities = len(state.get("recent", [])) + len(state.get("selected", [])) + len(state.get("previous", []))
    except (ValueError, TypeError):
        entities = None
    record = {"chat": chat_id, "sections": counts, "prompt_characters": sum(x["chars"] for x in counts.values()),
              "history_messages_sent": 0, "entities": entities,
              "content_tokens": sum(x["tokens"] for x in counts.values()) if all(x["tokens"] is not None for x in counts.values()) else None}
    logger.info("AI_CONTEXT %s", json.dumps(record, separators=(",", ":")))
    return record
