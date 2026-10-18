"""OpenAI-compatible NVIDIA transport. No provider-specific payload fields."""

import asyncio
import json
import logging
import time

import httpx

from app.core.config import settings
from app.services.ai_errors import AIProviderError

logger = logging.getLogger("drapemind.llm")


def provider_headers() -> dict[str, str]:
    if not settings.llm_api_key:
        raise AIProviderError(
            "Configura NVIDIA_API_KEY en backend/.env para habilitar el asistente."
        )
    return {"Authorization": f"Bearer {settings.llm_api_key}"}


async def complete(
    messages,
    *,
    tools=None,
    on_text=None,
    max_tokens=None,
    temperature=None,
    response_format=None,
    seed=None,
):
    """Assemble fragmented tool calls and emit only public content, never reasoning."""
    payload = {
        "model": settings.llm_model,
        "messages": messages,
        "stream": on_text is not None,
        "temperature": settings.AI_TEMPERATURE if temperature is None else temperature,
        "max_tokens": max_tokens or settings.AI_MAX_TOKENS,
    }
    if tools:
        payload.update(tools=tools, tool_choice="auto")
    # Provider-specific options are explicit and cannot replace protocol/security fields.
    if response_format:
        payload["response_format"] = response_format
    if seed is not None:
        payload["seed"] = seed
    for key, value in settings.NVIDIA_EXTRA_BODY.items():
        if key not in {
            "messages",
            "model",
            "tools",
            "tool_choice",
            "stream",
            "max_tokens",
        }:
            payload[key] = value
    started = time.monotonic()
    first_token = None
    content = ""
    calls = {}
    usage = {}
    finish_reason = None
    try:
        async with asyncio.timeout(settings.AI_AGENT_DEADLINE_SECONDS):
            async with httpx.AsyncClient(timeout=settings.AI_TIMEOUT_SECONDS) as client:
                if on_text is None:
                    response = await client.post(
                        f"{settings.llm_base_url}/chat/completions",
                        json=payload,
                        headers=provider_headers(),
                    )
                    response.raise_for_status()
                    data = response.json()
                    usage = data.get("usage") or {}
                    if data["choices"][0].get("finish_reason") not in {
                        "stop",
                        "tool_calls",
                    }:
                        raise AIProviderError(
                            "La respuesta de IA quedó incompleta. Puedes reintentar."
                        )
                    return data
                async with client.stream(
                    "POST",
                    f"{settings.llm_base_url}/chat/completions",
                    json=payload,
                    headers=provider_headers(),
                ) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        data = line[5:].strip()
                        if data == "[DONE]":
                            break
                        if not data:
                            continue
                        event = json.loads(data)
                        if event.get("error"):
                            raise AIProviderError(
                                "El proveedor de IA interrumpió la generación."
                            )
                        usage = event.get("usage") or usage
                        for choice in event.get("choices", []):
                            delta = choice.get("delta") or {}
                            text = delta.get("content") or ""
                            if text:
                                if first_token is None:
                                    first_token = time.monotonic() - started
                                content += text
                                await on_text(content)
                            for fragment in delta.get("tool_calls") or []:
                                index = fragment["index"]
                                if (
                                    index not in calls
                                    and len(calls) >= settings.AI_MAX_TOOL_CALLS
                                ):
                                    raise AIProviderError(
                                        "El modelo excedió el límite de herramientas."
                                    )
                                call = calls.setdefault(
                                    index,
                                    {
                                        "id": "",
                                        "type": "function",
                                        "function": {"name": "", "arguments": ""},
                                    },
                                )
                                if fragment.get("id"):
                                    call["id"] = fragment["id"]
                                function = fragment.get("function") or {}
                                call["function"]["name"] += function.get("name") or ""
                                call["function"]["arguments"] += (
                                    function.get("arguments") or ""
                                )
                                if len(call["function"]["arguments"]) > 16000:
                                    raise AIProviderError(
                                        "Los argumentos de herramienta excedieron el límite."
                                    )
                            finish_reason = choice.get("finish_reason") or finish_reason
        if finish_reason not in {"stop", "tool_calls"}:
            raise AIProviderError(
                "La respuesta de IA quedó incompleta. Puedes reintentar."
            )
        if calls and any(
            not call["id"] or not call["function"]["name"] for call in calls.values()
        ):
            raise AIProviderError(
                "El proveedor devolvió una llamada de herramienta incompleta."
            )
        message = {"role": "assistant", "content": content or None}
        if calls:
            message["tool_calls"] = [calls[index] for index in sorted(calls)]
        return {
            "choices": [{"message": message, "finish_reason": finish_reason}],
            "usage": usage,
        }
    except httpx.HTTPStatusError as exc:
        # Never include response bodies, credentials or customer prompts in errors/logs.
        raise AIProviderError(
            f"El proveedor de IA respondió HTTP {exc.response.status_code}. Revisa la clave, el modelo y sus permisos."
        ) from exc
    except (httpx.TimeoutException, TimeoutError) as exc:
        logger.warning("NVIDIA request timed out: %s", type(exc).__name__)
        raise AIProviderError(
            "NVIDIA tardó demasiado en responder. No pude verificar la consulta; puedes reintentar."
        ) from exc
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
        logger.warning("NVIDIA transport failed: %s", type(exc).__name__)
        raise AIProviderError(
            "No se pudo completar la conexión con la IA. Puedes reintentar."
        ) from exc
    finally:
        logger.info(
            "LLM model=%s ttft_ms=%s total_ms=%.0f usage=%s",
            settings.llm_model,
            round(first_token * 1000) if first_token is not None else None,
            (time.monotonic() - started) * 1000,
            usage,
        )


async def check_provider() -> dict:
    """A real completion/tool round trip; consumes a small amount of provider quota."""
    tool = {
        "type": "function",
        "function": {
            "name": "connection_probe",
            "description": "Comprobar el protocolo de herramientas.",
            "parameters": {
                "type": "object",
                "properties": {"value": {"type": "string"}},
                "required": ["value"],
            },
        },
    }
    messages = [
        {
            "role": "user",
            "content": "Invoca connection_probe con value=ok para comprobar la conexión.",
        }
    ]
    result = await complete(messages, tools=[tool], max_tokens=256)
    message = result["choices"][0]["message"]
    calls = message.get("tool_calls") or []
    if len(calls) != 1 or calls[0]["function"]["name"] != "connection_probe":
        raise AIProviderError(
            "El modelo respondió, pero no confirmó tool calling. Elige un modelo compatible."
        )
    if json.loads(calls[0]["function"]["arguments"]).get("value") != "ok":
        raise AIProviderError(
            "El modelo no respetó el contrato de la herramienta de prueba."
        )
    messages.extend(
        [
            message,
            {
                "role": "tool",
                "tool_call_id": calls[0]["id"],
                "content": '{"status":"ok"}',
            },
        ]
    )
    text = ""

    async def collect(value):
        nonlocal text
        text = value

    await complete(messages, on_text=collect, max_tokens=256)
    if not text.strip():
        raise AIProviderError(
            "Tool calling funciona, pero la prueba de streaming no devolvió texto."
        )
    return {
        "provider": "nvidia",
        "model": settings.NVIDIA_MODEL,
        "tool_calling": True,
        "streaming": True,
    }


async def provider_status() -> dict:
    healthy = False
    if settings.NVIDIA_API_KEY:
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                response = await client.get(
                    f"{settings.llm_base_url}/models", headers=provider_headers()
                )
                healthy = response.status_code == 200 and any(
                    model.get("id") == settings.NVIDIA_MODEL
                    for model in response.json().get("data", [])
                )
        except (httpx.HTTPError, ValueError):
            pass
    return {
        "provider": "nvidia",
        "configured": bool(settings.NVIDIA_API_KEY),
        "healthy": healthy,
        "model": settings.NVIDIA_MODEL,
    }
