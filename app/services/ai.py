import asyncio
import json
import logging
import re
import time
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import httpx
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import (
    AIInteraction, AIRecommendation, AISession, Product, ProductVariant, User,
)
from app.services.store import cart_payload, replace_cart_item, search_products
from app.services.ai_tools import TOOLS
from app.services.ai_agent import run_gemma_tool_agent
from app.services.ai_memory import build_session_summary, load_ai_memory, merge_ai_memory
from app.services.model_runtime import ModelRuntimeError, model_runtime

logger = logging.getLogger("drapemind.ai")

SYSTEM_PROMPT = (
    "Eres Altair, el Personal Stylist & Asesor de Imagen de DrapeMind Atelier. "
    "Usa solo datos verificados por FastAPI, no inventes stock ni precios y responde de forma elocuente, breve y accionable."
)


def sanitize_for_json(obj: Any) -> Any:
    """Recursively converts Decimals, datetimes, and non-serializable objects for JSON/WebSockets."""
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, (datetime, )):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {k: sanitize_for_json(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [sanitize_for_json(v) for v in obj]
    return obj


def compact_tool_results(tool_results: list[dict]) -> list[dict]:
    """Compacts tool results to strictly essential tokens so context never exceeds LLM limits."""
    compacted = []
    for tr in tool_results:
        tname = tr.get("name", "")
        tres = tr.get("result")
        if tname == "get_my_cart" and isinstance(tres, dict):
            items_summary = []
            for it in (tres.get("items") or []):
                items_summary.append({
                    "prenda": it.get("nombre"),
                    "color": it.get("color"),
                    "talla": it.get("talla"),
                    "precio_unitario": it.get("precio_unitario"),
                    "cantidad": it.get("cantidad"),
                    "subtotal": it.get("subtotal"),
                })
            complements_summary = []
            for it in (tres.get("sugerencias_complemento") or []):
                complements_summary.append({
                    "prenda": it.get("nombre"),
                    "precio": it.get("precio"),
                    "calidad": it.get("calidad"),
                })
            compacted.append({
                "herramienta": "carrito_usuario",
                "estado": tres.get("estado"),
                "total_items": tres.get("total_items"),
                "total_bs": tres.get("subtotal"),
                "prendas_en_carrito": items_summary,
                "complementos_sugeridos_tienda": complements_summary,
            })
        elif tname in ("search_products", "get_trending_pieces", "find_alternatives") and isinstance(tres, list):
            items_summary = []
            for it in tres[:5]:
                items_summary.append({
                    "prenda": it.get("nombre"),
                    "precio": it.get("precio"),
                    "calidad": it.get("calidad_nivel"),
                })
            compacted.append({
                "herramienta": tname,
                "opciones_encontradas": items_summary,
            })
        elif tname == "recommend_outfit" and isinstance(tres, dict):
            selected = tres.get("seleccion") or []
            outfit_summary = [
                {
                    "prenda": item.get("nombre"),
                    "precio": item.get("precio"),
                    "talla": item.get("talla"),
                    "color": item.get("color"),
                }
                for item in selected[:4]
            ]
            compacted.append({
                "herramienta": "outfit_sugerido",
                "ocasion": tres.get("ocasion"),
                "total_seleccion_bs": tres.get("seleccion_total"),
                "presupuesto_cumplido": tres.get("presupuesto_cumplido"),
                "piezas_seleccionadas": outfit_summary,
                "restricciones_solicitadas": tres.get("restricciones_solicitadas"),
                "restricciones_sin_stock": tres.get("restricciones_sin_stock"),
            })
        elif tname == "get_my_orders" and isinstance(tres, list):
            compacted.append({
                "herramienta": "mis_pedidos",
                "cantidad_pedidos": len(tres),
                "pedidos": [
                    {
                        "numero_pedido": o.get("id"),
                        "codigo": str(o.get("code", ""))[:8],
                        "estado": o.get("status"),
                        "total_bs": o.get("total_bob"),
                        "modalidad_entrega": o.get("delivery"),
                        "fecha_creacion": str(o.get("created_at", ""))[:10],
                    }
                    for o in tres[:5]
                ],
            })
        elif tname == "get_my_reservations" and isinstance(tres, list):
            compacted.append({
                "herramienta": "mis_reservas",
                "cantidad_reservas": len(tres),
                "reservas": [
                    {
                        "reserva_id": r.get("id"),
                        "codigo": str(r.get("code", ""))[:8],
                        "estado": r.get("status"),
                        "fecha_vencimiento": str(r.get("expires_at", ""))[:16],
                    }
                    for r in tres[:5]
                ],
            })
        elif tname == "analyze_styling":
            compacted.append({"herramienta": "analisis_estilo", "estado": "completado"})
        else:
            if isinstance(tres, dict):
                compacted.append({k: v for k, v in tres.items() if k in ("resumen", "total", "estado", "mensaje", "nombre")})
            elif isinstance(tres, list):
                compacted.append([{"nombre": x.get("nombre"), "precio": x.get("precio")} for x in tres[:4] if isinstance(x, dict)])
            else:
                compacted.append(str(tres)[:120])
    return compacted


def format_messages_for_gemma(messages: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Gemma models in llama.cpp do not support the 'system' role.
    Merge all system messages into the user turn to ensure 100% compatibility
    without triggering 'System role not supported' (HTTP 400).
    """
    clean_messages: list[dict[str, str]] = []
    system_parts: list[str] = []
    for m in messages:
        role = str(m.get("role", "user")).lower()
        content = str(m.get("content") or "").strip()
        if not content:
            continue
        if role == "system":
            system_parts.append(content)
        elif role in ("assistant", "model"):
            clean_messages.append({"role": "assistant", "content": content})
        else:
            clean_messages.append({"role": "user", "content": content})

    if system_parts:
        system_prefix = "\n\n".join(system_parts)
        if clean_messages and clean_messages[0]["role"] == "user":
            clean_messages[0]["content"] = f"[INSTRUCCIÓN DE ESTILO Y PERSONALIDAD]\n{system_prefix}\n\n[MENSAJE ACTUAL]\n{clean_messages[0]['content']}"
        else:
            clean_messages.insert(0, {"role": "user", "content": f"[INSTRUCCIÓN DE ESTILO Y PERSONALIDAD]\n{system_prefix}"})
    elif not clean_messages:
        clean_messages = [{"role": "user", "content": "Hola"}]

    return clean_messages


async def call_gemma(system: str, user: str) -> tuple[str, dict[str, int | None]]:
    combined = f"[INSTRUCCIÓN DE ESTILO Y PERSONALIDAD]\n{system}\n\n[MENSAJE ACTUAL]\n{user}" if system else user
    payload = {
        "model": settings.AI_MODEL,
        "messages": [{"role": "user", "content": combined}],
        "temperature": settings.AI_TEMPERATURE,
        "max_tokens": settings.AI_MAX_TOKENS,
        "stream": False,
    }
    headers = {"Authorization": f"Bearer {settings.AI_API_KEY}"}
    try:
        async with model_runtime.lease():
            async with httpx.AsyncClient(timeout=settings.AI_TIMEOUT_SECONDS) as client:
                response = await client.post(
                    f"{settings.AI_BASE_URL.rstrip('/')}/chat/completions",
                    json=payload,
                    headers=headers,
                )
                response.raise_for_status()
                data = response.json()
    except (httpx.HTTPError, KeyError, ValueError, ModelRuntimeError) as exc:
        raise HTTPException(
            status_code=503,
            detail="El servidor local de Gemma no esta disponible o devolvio una respuesta invalida",
        ) from exc
    usage = data.get("usage", {})
    return data["choices"][0]["message"]["content"], {
        "prompt_tokens": usage.get("prompt_tokens"),
        "completion_tokens": usage.get("completion_tokens"),
    }


def _extract_json(value: str) -> dict:
    value = value.strip()
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", value, re.DOTALL)
        if not match:
            return {"type": "finish"}
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            return {"type": "finish"}


async def _completion(
    messages: list[dict],
    max_tokens: int | None = None,
    stream: bool = False,
    response_format: dict[str, Any] | None = None,
    temperature: float | None = None,
):
    clean_messages = format_messages_for_gemma(messages)
    payload = {
        "model": settings.AI_MODEL,
        "messages": clean_messages,
        "temperature": temperature if temperature is not None else settings.AI_TEMPERATURE,
        "max_tokens": max_tokens or 160,
        "stream": stream,
        "stop": [
            "<end_of_turn>",
            "<eos>",
            "</s>",
            "<|im_end|>",
            "\nCLIENTE:",
            "\nCONSULTA:",
            "\nUSUARIO:",
        ],
    }
    if response_format:
        payload["response_format"] = response_format
    headers = {"Authorization": f"Bearer {settings.AI_API_KEY}"}
    client = httpx.AsyncClient(timeout=settings.AI_TIMEOUT_SECONDS)
    if not stream:
        try:
            response = await client.post(
                f"{settings.AI_BASE_URL.rstrip('/')}/chat/completions",
                json=payload,
                headers=headers,
            )
            if response.status_code == 400 and response_format:
                logger.warning("400 con response_format en llama-server, reintentando sin response_format")
                payload.pop("response_format", None)
                response = await client.post(
                    f"{settings.AI_BASE_URL.rstrip('/')}/chat/completions",
                    json=payload,
                    headers=headers,
                )
            if response.status_code >= 400:
                logger.error("LLM Error %d: %s", response.status_code, response.text)
            response.raise_for_status()
            return response.json()
        finally:
            await client.aclose()
    return client, payload, headers



async def run_agent_socket(db: Session, user: User, message: str, session_id: int | None, send) -> None:
    """Execute verified tools first and wake Gemma only when prose adds value."""
    started = time.perf_counter()
    session = get_ai_session(db, user.id, session_id)
    tool_results: list[dict] = []
    used_tools: list[str] = []
    answer_parts: list[str] = []

    user_name = (
        getattr(user, "nombre", None)
        or getattr(user, "username", None)
        or "Cliente"
    )

    try:
        await send({
            "type": "thought",
            "content": "Activando a Gemma con las tools disponibles para esta conversación..."
        })

        memory = load_ai_memory(session.resumen_contexto)
        was_ready = await model_runtime.is_healthy()
        await send(
            {
                "type": "model_status",
                "status": "ready" if was_ready else "loading",
                "session_id": session.id,
            }
        )
        # 1. Resolver y ejecutar las herramientas del atelier de forma ágil y verificada
        if getattr(run_gemma_tool_agent, "__name__", "") != "run_gemma_tool_agent":
            skill_res = await run_gemma_tool_agent(message, memory, user)
        else:
            from app.services.ai_skills.skill_registry import skill_registry
            skill = skill_registry.resolve(message, {"memory": memory, "user_id": user.id})
            try:
                skill_res = skill.execute(db, user, message, {"memory": memory, "user_id": user.id})
            except Exception as exc:
                logger.warning("Error ejecutando habilidad %s: %s", getattr(skill, "name", "unknown"), exc)
                skill_res = {
                    "requires_llm": True,
                    "action_items": [],
                    "direct_response": None,
                    "fallback_response": "He consultado el showroom atelier para tu solicitud.",
                    "focus_prompt": "Responde con elocuencia y estilo a la consulta del cliente.",
                    "presentation_mode": "text",
                }

        skill = SimpleNamespace(name="gemma_tool_agent")
        tool_name = skill_res.get("tool_name")
        tool_args = skill_res.get("tool_args") or {}
        tool_result = skill_res.get("tool_result")
        action_items = skill_res.get("action_items") or []
        presentation_mode = skill_res.get("presentation_mode") or (
            "mixed" if action_items else "text"
        )
        response_title = skill_res.get("response_title")
        notices = skill_res.get("notices") or []
        response_meta = skill_res.get("response_meta") or {}

        def _tool_thought_desc(name: str, args: dict | None = None) -> str:
            tool_def = TOOLS.get(name)
            if tool_def and tool_def.description:
                desc = tool_def.description.split(".")[0].strip()
                if args and args.get("query"):
                    return f"Buscando '{args['query']}' en showroom atelier..."
                if args and args.get("occasion"):
                    return f"Diseñando conjunto para ocasión '{args['occasion']}'..."
                return f"{desc}..."
            return f"Consultando {name.replace('_', ' ')} en atelier..."

        sub_tools = skill_res.get("composite_sub_tools")
        events_emitted = bool(skill_res.get("events_emitted"))
        if sub_tools and isinstance(sub_tools, list):
            for st in sub_tools:
                st_name = st.get("name")
                if not st_name:
                    continue
                st_args = st.get("args") or {}
                st_res = st.get("result")
                clean_st_res = sanitize_for_json(st_res)
                used_tools.append(st_name)
                tool_results.append({"name": st_name, "result": clean_st_res})
                if not events_emitted:
                    await send({"type": "thought", "content": _tool_thought_desc(st_name, st_args)})
                    await send({
                        "type": "tool_start",
                        "name": st_name,
                        "arguments": sanitize_for_json(st_args),
                    })
                    await send({
                        "type": "tool_result",
                        "name": st_name,
                        "result": clean_st_res,
                    })
        elif tool_name:
            await send({"type": "thought", "content": _tool_thought_desc(tool_name, tool_args)})
            await send(
                {
                    "type": "tool_start",
                    "name": tool_name,
                    "arguments": sanitize_for_json(tool_args),
                }
            )
            clean_tool_result = sanitize_for_json(tool_result)
            used_tools.append(tool_name)
            tool_results.append({"name": tool_name, "result": clean_tool_result})
            await send(
                {
                    "type": "tool_result",
                    "name": tool_name,
                    "result": clean_tool_result,
                }
            )

        if action_items:
            await send({
                "type": "thought",
                "content": f"Preparando {len(action_items)} resultado(s) interactivo(s) para la conversación..."
            })

        suggested_actions = skill_res.get("suggested_actions") or []

        await send(
            {
                "type": "presentation",
                "mode": presentation_mode,
                "title": response_title,
                "card_count": len(action_items),
                "notices": sanitize_for_json(notices),
                "response_meta": sanitize_for_json(response_meta),
                "suggested_actions": sanitize_for_json(suggested_actions),
            }
        )

        if not skill_res.get("requires_llm"):
            direct_text = skill_res.get("direct_response") or skill_res.get("fallback_response") or ""
            if not direct_text:
                if action_items:
                    direct_text = (
                        f"He preparado {len(action_items)} prenda(s) y combinaciones del showroom "
                        f"con stock y disponibilidad confirmados en FastAPI."
                    )
                else:
                    direct_text = "He consultado la información del atelier para tu solicitud."
            for index in range(0, len(direct_text), 36):
                chunk = direct_text[index:index + 36]
                answer_parts.append(chunk)
                await send({"type": "token", "content": chunk})
                await asyncio.sleep(0.015)
        else:
            was_ready = await model_runtime.is_healthy()
            await send(
                {
                    "type": "model_status",
                    "status": "ready" if was_ready else "loading",
                    "session_id": session.id,
                }
            )
            user_name = (
                getattr(user, "nombre", None)
                or getattr(user, "username", None)
                or "Cliente"
            )
            focus_prompt = skill_res.get("focus_prompt") or (
                "Brinda una asesoría de moda completa, argumentada y distinguida."
            )

            items_catalog_lines = []
            for it in action_items:
                nom = it.get("nombre")
                pr = it.get("precio", 0)
                tal = it.get("talla")
                mot = it.get("motivo") or ""
                extra = f" (Talla {tal})" if tal else ""
                items_catalog_lines.append(f"- {nom}{extra}: Bs {pr:.2f} [{mot}]")
            items_catalog_text = "\n".join(items_catalog_lines) if items_catalog_lines else "No hay prendas específicas seleccionadas."

            final_messages = [
                {
                    "role": "system",
                    "content": (
                        "Eres Altair, Personal Stylist e Inteligencia Artificial de DrapeMind Atelier.\n"
                        "DIRECTRICES GENERALES DE RESPUESTA:\n"
                        "1. ADAPTABILIDAD TOTAL Y FIDELIDAD AL PROMPT: Cumple estrictamente con el tono, formato, estilo o personalidad que el usuario te solicite en su mensaje (humor, rima, poesía, sarcasmo, ironía, concisión extrema, formalidad, análisis técnico, o cualquier otro estilo). Adopta de inmediato ese estilo con naturalidad e ingenio.\n"
                        "2. INTEGRACIÓN DE PRENDAS Y PRECIOS: Fundamenta tu asesoría en los datos reales del showroom (prendas verificadas y sus precios en Bolivianos Bs). Cita los nombres y precios reales integrándolos fluidamente en el formato que el usuario pidió.\n"
                        "3. NATURALIDAD HUMANA: No uses saludos robóticos ni fórmulas repetitivas ('Estimado cliente...', 'A continuación te presento...'). Ve directo al grano y habla con carisma y soltura.\n"
                        "4. PROHIBICIÓN ESTRICTA: Cero emojis o emoticonos bajo cualquier circunstancia."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"CLIENTE: {user_name}\n"
                        f"CONSULTA DEL CLIENTE: {message}\n\n"
                        f"DATOS DEL ATELIER (Prendas y precios verificados):\n{items_catalog_text}\n\n"
                        f"ENFOQUE: {focus_prompt}\n\n"
                        "Responde a la consulta del cliente cumpliendo con fidelidad todas sus instrucciones de tono, contenido y estilo:"
                    ),
                },
            ]
            max_tokens = max(80, min(240, int(skill_res.get("llm_max_tokens") or 160)))
            target_temp = float(settings.AI_TEMPERATURE or 0.65)
            if target_temp < 0.6:
                target_temp = 0.65

            try:
                async with model_runtime.lease():
                    await send(
                        {
                            "type": "model_status",
                            "status": "ready",
                            "session_id": session.id,
                        }
                    )
                    client, payload, headers = await _completion(
                        final_messages,
                        max_tokens=max_tokens,
                        stream=True,
                        temperature=target_temp,
                    )
                    try:
                        async with client.stream(
                            "POST",
                            f"{settings.AI_BASE_URL.rstrip('/')}/chat/completions",
                            json=payload,
                            headers=headers,
                        ) as response:
                            if response.status_code >= 400:
                                error_body = await response.aread()
                                logger.error(
                                    "LLM Stream Error %d: %s",
                                    response.status_code,
                                    error_body.decode("utf-8", errors="ignore"),
                                )
                            response.raise_for_status()
                            async for line in response.aiter_lines():
                                if not line.startswith("data:"):
                                    continue
                                raw = line[5:].strip()
                                if raw == "[DONE]":
                                    break
                                try:
                                    event = json.loads(raw)
                                    delta = event["choices"][0]["delta"]
                                    chunk = delta.get("content") or delta.get("reasoning_content") or ""
                                except (json.JSONDecodeError, KeyError, IndexError):
                                    continue
                                if chunk:
                                    answer_parts.append(chunk)
                                    await send({"type": "token", "content": chunk})
                    except Exception as stream_err:
                        logger.warning("Error durante streaming LLM: %s. Intentando completado directo.", stream_err)
                    finally:
                        await client.aclose()

                    # Fallback inmediato a completado no-streaming si el stream vino vacío o falló
                    if not "".join(answer_parts).strip():
                        try:
                            logger.info("Stream vacío, reintentando con POST directo a llama-server...")
                            async with httpx.AsyncClient(timeout=25.0) as direct_client:
                                direct_payload = {**payload, "stream": False}
                                resp = await direct_client.post(
                                    f"{settings.AI_BASE_URL.rstrip('/')}/chat/completions",
                                    json=direct_payload,
                                    headers=headers,
                                )
                                if resp.status_code == 200:
                                    data = resp.json()
                                    msg = data["choices"][0]["message"]
                                    direct_text = msg.get("content") or msg.get("reasoning_content") or ""
                                    if direct_text and direct_text.strip():
                                        for idx in range(0, len(direct_text), 12):
                                            c = direct_text[idx:idx + 12]
                                            answer_parts.append(c)
                                            await send({"type": "token", "content": c})
                                            await asyncio.sleep(0.01)
                        except Exception as direct_err:
                            logger.warning("Fallo en completado directo: %s", direct_err)
            except (ModelRuntimeError, httpx.HTTPError, Exception) as exc:
                logger.warning("Gemma runtime lease no disponible o falló en síntesis: %s", exc)
                if not "".join(answer_parts).strip():
                    fallback_text = str(skill_res.get("fallback_response") or skill_res.get("direct_response") or "Aquí tienes las opciones seleccionadas según tu solicitud.")
                    for index in range(0, len(fallback_text), 48):
                        chunk = fallback_text[index:index + 48]
                        answer_parts.append(chunk)
                        await send({"type": "token", "content": chunk})

        if not "".join(answer_parts).strip() and skill_res.get("fallback_response"):
            fallback_text = str(skill_res["fallback_response"])
            for index in range(0, len(fallback_text), 48):
                chunk = fallback_text[index:index + 48]
                answer_parts.append(chunk)
                await send({"type": "token", "content": chunk})

        answer = "".join(answer_parts).strip()
        interaction = _save_interaction(
            db,
            session,
            "CHAT",
            message,
            answer or f"[{presentation_mode}: {len(action_items)} cards]",
            ",".join(used_tools) or "skill:" + skill.name,
            started,
            {"prompt_tokens": None, "completion_tokens": None},
        )
        recommended_product_ids = [
            int(item["id"])
            for item in action_items
            if item.get("accion") == "AGREGAR" and item.get("id")
        ]
        memory = merge_ai_memory(
            memory,
            skill_res.get("memory_updates"),
            recommended_product_ids,
        )
        session.resumen_contexto = build_session_summary(
            (
                f"Usuario: {message[:300]}\nAsistente: "
                f"{(answer or response_title or presentation_mode)[:500]}"
            ),
            memory,
        )
        db.commit()
        duration_ms = max(0, int((time.perf_counter() - started) * 1000))

        await send(
            {
                "type": "done",
                "session_id": session.id,
                "interaction_id": interaction.id,
                "tools": used_tools,
                "action_items": sanitize_for_json(action_items[:6]),
                "presentation_mode": presentation_mode,
                "response_title": response_title,
                "duration_ms": duration_ms,
                "notices": sanitize_for_json(notices),
                "response_meta": sanitize_for_json(response_meta),
                "suggested_actions": sanitize_for_json(suggested_actions),
            }
        )
    except Exception:
        db.rollback()
        raise


def get_ai_session(db: Session, user_id: int, session_id: int | None) -> AISession:
    if session_id:
        try:
            session = db.scalar(
                select(AISession).where(AISession.id == int(session_id), AISession.usuario_id == user_id)
            )
            if session and session.estado == "ACTIVA":
                return session
        except (ValueError, TypeError):
            pass
    session = AISession(usuario_id=user_id, estado="ACTIVA")
    db.add(session)
    db.flush()
    return session


def _available_candidates(db: Session, limit: int = 30) -> list[dict[str, Any]]:
    return search_products(db, only_available=True, limit=limit)


def _save_interaction(
    db: Session,
    session: AISession,
    kind: str,
    message: str,
    answer: str,
    tool: str,
    started: float,
    usage: dict[str, int | None],
    status: str = "OK",
) -> AIInteraction:
    session.last_activity_at = datetime.now(timezone.utc)
    interaction = AIInteraction(
        sesion_id=session.id, tipo=kind, mensaje_usuario=message, respuesta=answer,
        tool_principal=tool, duracion_ms=max(0, int((time.perf_counter() - started) * 1000)),
        tokens_entrada=usage.get("prompt_tokens"), tokens_salida=usage.get("completion_tokens"),
        modelo=settings.AI_MODEL, estado=status,
    )
    db.add(interaction)
    db.flush()
    return interaction


def _pick_variants(db: Session, product_ids: list[int]) -> list[dict]:
    if not product_ids:
        return []
    rows = db.execute(
        select(ProductVariant, Product)
        .join(Product, Product.id == ProductVariant.producto_id)
        .where(
            Product.id.in_(product_ids), ProductVariant.activo.is_(True),
            ProductVariant.stock_total > ProductVariant.stock_reservado,
        )
        .order_by(Product.id, ProductVariant.id)
    ).all()
    seen: set[int] = set()
    output = []
    for variant, product in rows:
        if product.id in seen:
            continue
        seen.add(product.id)
        output.append({
            "producto_id": product.id, "variante_id": variant.id, "nombre": product.nombre,
            "precio": str(product.precio), "calidad": product.calidad_nivel,
            "sku": variant.sku, "color": variant.color, "talla": variant.talla,
            "stock": variant.stock_total - variant.stock_reservado,
        })
    return output


async def run_ai_action(
    db: Session,
    user: User,
    action: str,
    message: str,
    session_id: int | None = None,
    budget: Decimal | None = None,
    base_product_id: int | None = None,
) -> dict:
    started = time.perf_counter()
    session = get_ai_session(db, user.id, session_id)
    tool = "search_products"
    kind = "CHAT"
    products: list[dict[str, Any]] = []
    recommendations: list[dict[str, Any]] = []

    if action == "chat":
        cart = cart_payload(db, user.id)
        products = _available_candidates(db, 12)
        tool = "get_my_cart + search_products"
        prompt = f"MENSAJE: {message}\nCARRITO: {json.dumps(cart, default=str)}\nCATALOGO: {json.dumps(products, default=str)}"
    elif action == "search":
        kind = "PRODUCT_SEARCH"
        extractor, _ = await call_gemma(
            "Extrae solo palabras clave concretas de ropa de la consulta. Devuelve una frase corta, sin explicacion.",
            message,
        )
        products = search_products(db, query=extractor.strip()[:150], only_available=True, limit=20)
        if not products:
            products = search_products(db, query=message.strip()[:150], only_available=True, limit=20)
        prompt = f"Consulta: {message}\nProductos encontrados por FastAPI: {json.dumps(products, default=str)}\nResume los mejores resultados."
    elif action in {"outfit", "complete"}:
        kind = "COMPLETE_OUTFIT" if action == "complete" else "GENERATE_OUTFIT"
        tool = "search_products + get_stock"
        candidates = _available_candidates(db, 30)
        if budget is not None:
            candidates = [p for p in candidates if p["precio"] <= budget]
        products = _pick_variants(db, [p["id"] for p in candidates])
        if base_product_id:
            base = db.get(Product, base_product_id)
            if not base:
                raise HTTPException(404, "Producto base no encontrado")
            message = f"{message}. Prenda base: {base.nombre} (id {base.id})"
        prompt = (
            f"Solicitud: {message}\nOpciones reales: {json.dumps(products, default=str)}\n"
            "Propone un outfit coherente usando de 2 a 4 opciones e incluye sus IDs."
        )
    elif action in {"style", "value"}:
        kind = "STYLE_CHECK" if action == "style" else "VALUE_CHECK"
        tool = "get_my_cart + find_alternatives"
        cart = cart_payload(db, user.id)
        if not cart["items"]:
            raise HTTPException(409, "El carrito esta vacio")
        products = _available_candidates(db, 30)
        prompt = (
            f"Objetivo: {message}\nCarrito real: {json.dumps(cart, default=str)}\n"
            f"Alternativas reales: {json.dumps(products, default=str)}\n"
            "Analiza el carrito y propone mejoras concretas solo con esos productos."
        )
    else:
        raise HTTPException(400, "Accion de IA no soportada")

    try:
        answer, usage = await call_gemma(SYSTEM_PROMPT, prompt)
        interaction = _save_interaction(db, session, kind, message, answer, tool, started, usage)
        if action in {"outfit", "complete"}:
            rec_type = "COMPLETAR_OUTFIT" if action == "complete" else "OUTFIT"
            roles = ["TOP", "BOTTOM", "SHOES", "OUTERWEAR"]
            for index, candidate in enumerate(products[:4]):
                rec = AIRecommendation(
                    interaccion_id=interaction.id, tipo=rec_type, rol=roles[index],
                    producto_origen_id=base_product_id,
                    producto_recomendado_id=candidate["producto_id"],
                    variante_recomendada_id=candidate["variante_id"],
                    score=Decimal("0.7500"), motivo_corto="Seleccionado por disponibilidad y coherencia del conjunto",
                )
                db.add(rec)
                db.flush()
                recommendations.append({"id": rec.id, **candidate, "tipo": rec_type, "rol": roles[index]})
        elif action == "value":
            cart = cart_payload(db, user.id)
            for item in cart["items"]:
                origin = db.get(Product, item["producto_id"])
                alternative = db.execute(
                    select(ProductVariant, Product)
                    .join(Product, Product.id == ProductVariant.producto_id)
                    .where(
                        Product.categoria_id == origin.categoria_id,
                        Product.id != origin.id,
                        Product.activo.is_(True),
                        Product.precio < origin.precio,
                        ProductVariant.activo.is_(True),
                        ProductVariant.stock_total > ProductVariant.stock_reservado,
                    )
                    .order_by((Product.calidad_nivel / Product.precio).desc())
                    .limit(1)
                ).first()
                if alternative:
                    variant, product = alternative
                    saving = max(Decimal("0"), origin.precio - product.precio)
                    rec = AIRecommendation(
                        interaccion_id=interaction.id, tipo="REEMPLAZO_VALOR",
                        producto_origen_id=origin.id, variante_origen_id=item["variante_id"],
                        producto_recomendado_id=product.id, variante_recomendada_id=variant.id,
                        score=Decimal("0.8000"), ahorro=saving,
                        motivo_corto="Mejor relacion calidad/precio con stock disponible",
                    )
                    db.add(rec)
                    db.flush()
                    recommendations.append({
                        "id": rec.id, "item_id": item["id"], "producto_id": product.id,
                        "variante_id": variant.id, "nombre": product.nombre, "ahorro": str(saving),
                    })
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    return {
        "sesion_id": session.id, "interaccion_id": interaction.id, "respuesta": answer,
        "productos": products, "recomendaciones": recommendations, "modelo": settings.AI_MODEL,
    }


def apply_recommendation(db: Session, user_id: int, recommendation_id: int) -> dict:
    recommendation = db.scalar(
        select(AIRecommendation)
        .join(AIInteraction, AIInteraction.id == AIRecommendation.interaccion_id)
        .join(AISession, AISession.id == AIInteraction.sesion_id)
        .where(AIRecommendation.id == recommendation_id, AISession.usuario_id == user_id)
    )
    if not recommendation:
        raise HTTPException(404, "Recomendacion no encontrada")
    if recommendation.aplicada:
        raise HTTPException(409, "La recomendacion ya fue aplicada")
    if not recommendation.variante_origen_id or not recommendation.variante_recomendada_id:
        raise HTTPException(409, "Esta recomendacion no representa un reemplazo de carrito")
    cart = cart_payload(db, user_id)
    item = next((x for x in cart["items"] if x["variante_id"] == recommendation.variante_origen_id), None)
    if not item:
        raise HTTPException(409, "La prenda original ya no esta en el carrito")
    updated = replace_cart_item(db, user_id, item["id"], recommendation.variante_recomendada_id)
    recommendation.aceptada = True
    recommendation.aplicada = True
    recommendation.applied_at = datetime.now(timezone.utc)
    db.commit()
    return updated
