"""Conversation and commerce integration for the NVIDIA assistant."""

from datetime import datetime, timezone
from decimal import Decimal
import logging
import time
from typing import Any
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import (
    AIInteraction,
    AIRecommendation,
    AISession,
    Product,
    ProductVariant,
    User,
    UserStyleProfile,
)
from app.services.ai_errors import AIProviderError
from app.services.ai_memory import build_session_summary, load_ai_memory
from app.services.chat_context import observe_cards, read_context, update_context
from app.services.chat_sessions import owned_session
from app.services.llm_provider import complete
from app.services.nvidia_agent import run_nvidia_agent
from app.services.personal_shopping import shopping_context
from app.services.chat_context import merge_turn_constraints
from app.services.store import cart_payload, get_product_detail, replace_cart_item

logger = logging.getLogger("drapemind.ai")


def sanitize_for_json(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: sanitize_for_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [sanitize_for_json(item) for item in value]
    return value


async def call_nvidia(
    system: str,
    user: str,
    *,
    temperature=None,
    seed=None,
    response_format=None,
    max_tokens=None,
    model=None,
):
    result = await complete(
        [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=temperature,
        response_format=response_format,
        max_tokens=max_tokens,
        seed=seed,
    )
    text = result["choices"][0]["message"].get("content")
    if not isinstance(text, str) or not text.strip():
        raise AIProviderError("Altair no devolvió una respuesta. Puedes reintentar.")
    return text, {**(result.get("usage") or {}), "model": settings.NVIDIA_MODEL}


def get_ai_session(db: Session, user_id: int, session_id: int | None) -> AISession:
    if session_id is not None:
        try:
            return owned_session(db, user_id, int(session_id))
        except (TypeError, ValueError) as exc:
            raise HTTPException(404, "Conversación no encontrada") from exc
    session = AISession(usuario_id=user_id, estado="ACTIVA")
    db.add(session)
    db.flush()
    return session


async def run_agent_socket(
    db: Session,
    user: User,
    message: str,
    session_id: int | None,
    send,
    task_context=None,
    action="chat",
) -> None:
    started = time.perf_counter()
    session = get_ai_session(db, user.id, session_id)
    memory = read_context(load_ai_memory(session.resumen_contexto))
    profile_context = shopping_context(db, user)
    recent = list(
        db.scalars(
            select(AIInteraction)
            .where(AIInteraction.sesion_id == session.id)
            .order_by(AIInteraction.id.desc())
            .limit(6)
        )
    )
    history = []
    for turn in reversed(recent):
        history.extend(
            [
                {"role": "user", "content": (turn.mensaje_usuario or "")[:2000]},
                {"role": "assistant", "content": (turn.respuesta or "")[:2500]},
            ]
        )
    await send({"type": "model_status", "status": "loading", "session_id": session.id})
    try:
        result = await run_nvidia_agent(
            db,
            user,
            message,
            memory.model_dump(),
            send,
            history=history,
            task_context=task_context,
            shopping_profile=profile_context,
        )
        answer = result["direct_response"]
        cards = sanitize_for_json(result.get("action_items") or [])
        verified = sanitize_for_json(result.get("verified_products") or cards)
        suggestions = result.get("suggested_actions") or []
        presentation = "mixed" if cards or result.get("ui_blocks") else "text"
        await send(
            {
                "type": "presentation",
                "mode": presentation,
                "title": "Altair",
                "response_meta": result.get("response_meta") or {},
                "suggested_actions": suggestions,
                "ui_blocks": result.get("ui_blocks") or [],
            }
        )
        await send({"type": "answer_snapshot", "content": answer})
        tools = [step["name"] for step in result.get("composite_sub_tools") or []]
        usage = result.get("usage") or {}
        duration = round((time.perf_counter() - started) * 1000)
        interaction = AIInteraction(
            sesion_id=session.id,
            tipo={
                "search": "PRODUCT_SEARCH",
                "outfit": "GENERATE_OUTFIT",
                "complete": "COMPLETE_OUTFIT",
                "style": "STYLE_CHECK",
                "value": "VALUE_CHECK",
            }.get(action, "CHAT"),
            mensaje_usuario=message,
            respuesta=result.get("history_response") or answer,
            tool_principal=(",".join(tools) or "conversation")[:250],
            duracion_ms=duration,
            tokens_entrada=usage.get("prompt_tokens"),
            tokens_salida=usage.get("completion_tokens"),
            modelo=settings.NVIDIA_MODEL,
            estado="OK",
        )
        db.add(interaction)
        db.flush()
        recommendations = _save_replacements(
            db, user.id, interaction.id, result.get("composite_sub_tools") or []
        )
        db.refresh(session)
        latest = read_context(load_ai_memory(session.resumen_contexto))
        latest = update_context(latest, {"facts": memory.facts})
        latest = merge_turn_constraints(latest, memory, result.get("chat_context"))
        session.resumen_contexto = build_session_summary(
            "", observe_cards(latest, verified).model_dump()
        )
        session.last_activity_at = datetime.now(timezone.utc)
        db.commit()
        await send(
            {
                "type": "done",
                "session_id": session.id,
                "interaction_id": interaction.id,
                "tools": tools,
                "action_items": cards,
                "verified_products": verified,
                "presentation_mode": presentation,
                "response_title": "Altair",
                "duration_ms": duration,
                "suggested_actions": suggestions,
                "recommendations": recommendations,
                "response_meta": result.get("response_meta") or {},
                "ui_blocks": result.get("ui_blocks") or [],
            }
        )
        logger.info(
            "AI_TURN session=%s duration_ms=%s tools=%s", session.id, duration, tools
        )
    except TimeoutError as exc:
        db.rollback()
        raise AIProviderError(
            "Altair tardó más de lo esperado. Puedes reintentar."
        ) from exc
    except BaseException:
        db.rollback()
        raise


def _save_replacements(db, user_id, interaction_id, steps):
    """Persist only observed, in-stock, same-size savings against this user's real cart."""
    alternatives = [
        step
        for step in steps
        if step["name"] == "find_alternatives" and isinstance(step.get("result"), list)
    ]
    if not alternatives:
        return []
    cart = cart_payload(db, user_id)
    recommendations, seen = [], set()
    for step in alternatives:
        origins = [
            item
            for item in cart["items"]
            if item["producto_id"] == step["args"].get("product_id")
        ]
        for candidate in step["result"]:
            variant = db.get(ProductVariant, candidate.get("variant_id"))
            if (
                not variant
                or not variant.activo
                or variant.stock_total <= variant.stock_reservado
            ):
                continue
            target = db.get(Product, variant.producto_id)
            if (
                not target
                or not target.activo
                or target.id != candidate.get("product_id")
            ):
                continue
            for origin in origins:
                key = (origin["variante_id"], variant.id)
                quantity = origin["cantidad"]
                saving = (
                    Decimal(str(origin["precio_unitario"])) - target.precio
                ) * quantity
                if (
                    key in seen
                    or origin["talla"] != variant.talla
                    or saving <= 0
                    or variant.stock_total - variant.stock_reservado < quantity
                ):
                    continue
                seen.add(key)
                record = AIRecommendation(
                    interaccion_id=interaction_id,
                    grupo_uuid=uuid4(),
                    tipo="REEMPLAZO_AHORRO",
                    producto_origen_id=origin["producto_id"],
                    variante_origen_id=origin["variante_id"],
                    producto_recomendado_id=target.id,
                    variante_recomendada_id=variant.id,
                    ahorro=saving,
                    motivo_corto="Alternativa consultada por Altair con ahorro calculado por la tienda.",
                )
                db.add(record)
                db.flush()
                recommendations.append(
                    {
                        "id": record.id,
                        "nombre_original": origin["nombre"],
                        "nombre": target.nombre,
                        "precio_original": float(origin["precio_unitario"]),
                        "precio_recomendado": float(target.precio),
                        "ahorro": float(saving),
                        "color": variant.color,
                        "talla": variant.talla,
                        "variante_id": variant.id,
                    }
                )
    return recommendations


async def run_ai_action(
    db: Session,
    user: User,
    action: str,
    message: str,
    session_id=None,
    budget=None,
    base_product_id=None,
    model_choice=None,
) -> dict:
    requests = {
        "chat": "",
        "search": "Busca prendas con estas preferencias: ",
        "outfit": "Recomienda un outfit con prendas verificadas: ",
        "complete": "Completa un outfit desde la prenda indicada: ",
        "style": "Consulta mi carrito y analiza su estilo: ",
        "value": "Consulta mi carrito y busca alternativas de calidad/precio: ",
    }
    if action not in requests:
        raise HTTPException(400, "Acción de IA no soportada")
    query = requests[action] + message
    if budget is not None:
        query += f". Presupuesto máximo: {budget} BOB."
    if base_product_id is not None:
        query += f". Producto base: {base_product_id}. Consulta sus detalles."
    events = []

    async def collect(event):
        events.append(event)

    try:
        await run_agent_socket(db, user, query, session_id, collect, action=action)
    except AIProviderError as exc:
        raise HTTPException(503, str(exc)) from exc
    done = next(event for event in reversed(events) if event["type"] == "done")
    interaction = db.get(AIInteraction, done["interaction_id"])
    products = [
        {
            **get_product_detail(db, item["id"]),
            **item,
            "en_carrito": item["accion"] == "QUITAR",
        }
        for item in done.get("verified_products", done["action_items"])
        if item["accion"] in {"AGREGAR", "QUITAR"}
    ]
    recommendations = done.get("recommendations") or (
        [product for product in products if not product["en_carrito"]]
        if action == "style"
        else []
    )
    return {
        "sesion_id": done["session_id"],
        "interaccion_id": done["interaction_id"],
        "respuesta": interaction.respuesta,
        "productos": products,
        "recomendaciones": recommendations,
        "modelo": settings.NVIDIA_MODEL,
    }


def apply_recommendation(db: Session, user_id: int, recommendation_id: int) -> dict:
    recommendation = db.scalar(
        select(AIRecommendation)
        .join(AIInteraction, AIInteraction.id == AIRecommendation.interaccion_id)
        .join(AISession, AISession.id == AIInteraction.sesion_id)
        .where(
            AIRecommendation.id == recommendation_id, AISession.usuario_id == user_id
        )
    )
    if not recommendation:
        raise HTTPException(404, "Recomendación no encontrada")
    if recommendation.aplicada:
        raise HTTPException(409, "La recomendación ya fue aplicada")
    if (
        not recommendation.variante_origen_id
        or not recommendation.variante_recomendada_id
    ):
        raise HTTPException(
            409, "Esta recomendación no representa un reemplazo de carrito"
        )
    cart = cart_payload(db, user_id)
    item = next(
        (
            item
            for item in cart["items"]
            if item["variante_id"] == recommendation.variante_origen_id
        ),
        None,
    )
    if not item:
        raise HTTPException(409, "La prenda original ya no está en el carrito")
    updated = replace_cart_item(
        db, user_id, item["id"], recommendation.variante_recomendada_id
    )
    recommendation.aceptada = True
    recommendation.aplicada = True
    recommendation.applied_at = datetime.now(timezone.utc)
    db.commit()
    return updated
