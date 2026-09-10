import asyncio
import json
import re
from typing import Any, Awaitable, Callable

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.models import User
from app.core.config import settings
from app.services.agent_stream import compact_observation
from app.services.model_runtime import ModelRuntimeError
from app.services.ai_tools import TOOLS, ToolContext, execute_tool, tool_catalog
from app.services.store import get_product_detail
from app.services.chat_context import read_context, update_context, observe_cards, serialize_observation
from app.services.context_prompt import build_messages, prompt_sections


CompleteFn = Callable[..., Awaitable[dict[str, Any]]]
EventFn = Callable[[dict[str, Any]], Awaitable[None]]


def _argument_hint(schema: dict) -> str:
    if schema.get("enum"):
        return "|".join(map(str, schema["enum"]))
    if schema.get("anyOf"):
        return "|".join(_argument_hint(item) for item in schema["anyOf"] if item.get("type") != "null")
    if schema.get("type") == "array":
        return f"list[{_argument_hint(schema.get('items', {}))}]"
    return schema.get("type", "object")


async def _with_keepalive(coro: Awaitable[Any], emit: EventFn | None, thoughts: list[str], interval: float = 6.0) -> Any:
    async def _ticker():
        idx = 0
        while True:
            await asyncio.sleep(interval)
            if emit:
                try:
                    await emit({"type": "progress", "content": thoughts[idx % len(thoughts)]})
                except Exception:
                    pass
            idx += 1

    ticker_task = asyncio.create_task(_ticker())
    try:
        return await coro
    finally:
        ticker_task.cancel()
        try:
            await ticker_task
        except asyncio.CancelledError:
            pass


def _json_decision(raw: str) -> dict[str, Any] | None:
    raw = raw.strip()
    if raw.startswith("```json") and raw.endswith("```"):
        raw = raw[len("```json"):-3].strip()
    try:
        value = json.loads(raw)
        return value if isinstance(value, dict) else None
    except json.JSONDecodeError:
        for match in re.finditer(r"\{", raw):
            try:
                value, _ = json.JSONDecoder().raw_decode(raw[match.start():])
                if isinstance(value, dict) and value.get("type") in {"tool", "finish"}:
                    return value
            except json.JSONDecodeError:
                continue
    # Si Gemma respondió en prosa natural sin envolver en JSON:
    if raw and not raw.startswith("{"):
        return {
            "type": "finish",
            "answer": raw,
            "title": "Asesoría DrapeMind Atelier",
            "presentation": "mixed",
        }
    return None


def _available_variant(detail: dict[str, Any], requested_size: str | None) -> dict[str, Any] | None:
    variants = [
        variant
        for variant in detail.get("variantes") or []
        if variant.get("activo") and (variant.get("stock_disponible") or 0) > 0
    ]
    if requested_size:
        exact = next(
            (
                variant
                for variant in variants
                if str(variant.get("talla") or "").upper() == requested_size.upper()
            ),
            None,
        )
        return exact
    return variants[0] if variants else None


def _product_card(
    db: Session,
    product: dict[str, Any],
    requested_size: str | None = None,
) -> dict[str, Any] | None:
    product_id = product.get("id") or product.get("producto_id") or product.get("product_id")
    if not product_id:
        return None
    detail = get_product_detail(db, int(product_id))
    variant = _available_variant(detail, requested_size)
    if not variant:
        return None
    return {
        "id": int(product_id),
        "variante_id": variant.get("id"),
        "nombre": detail.get("nombre") or product.get("nombre") or product.get("name"),
        "precio": float(detail.get("precio") or product.get("precio") or product.get("price") or 0),
        "color": variant.get("color"),
        "talla": variant.get("talla"),
        "sku": variant.get("sku"),
        "imagen": variant.get("imagen") or ((detail.get("imagenes") or [None])[0]),
        "accion": "AGREGAR",
        "motivo": f"Stock real verificado · Calidad Q{detail.get('calidad_nivel') or 3}",
    }


def _cards_from_tool(
    db: Session,
    tool_name: str,
    arguments: dict[str, Any],
    result: Any,
) -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []
    requested_size = arguments.get("size")
    if tool_name in {
        "search_products",
        "get_trending_pieces",
        "get_new_arrivals",
        "get_most_expensive_product",
        "find_alternatives",
        "get_my_favorites",
    } and isinstance(result, list):
        for product in result[:6]:
            if isinstance(product, dict):
                card = _product_card(db, product, requested_size)
                if card:
                    cards.append(card)
    elif tool_name == "get_product_detail" and isinstance(result, dict):
        card = _product_card(db, result, requested_size)
        if card:
            cards.append(card)
    elif tool_name == "recommend_outfit" and isinstance(result, dict):
        total = 0.0
        budget = arguments.get("max_budget")
        for key in (
            "tops_sugeridos",
            "inferiores_sugeridos",
            "calzado_sugerido",
            "complementos_abrigos",
        ):
            options = result.get(key) or []
            if not options:
                continue
            option = options[0]
            price = float(option.get("precio") or 0)
            if budget is not None and total + price > float(budget):
                continue
            total += price
            cards.append(
                {
                    "id": option.get("producto_id") or option.get("id"),
                    "variante_id": option.get("variante_id"),
                    "nombre": option.get("nombre"),
                    "precio": price,
                    "color": option.get("color"),
                    "talla": option.get("talla"),
                    "imagen": option.get("imagen"),
                    "accion": "AGREGAR",
                    "motivo": "Variante y stock verificados por FastAPI",
                }
            )
        result["seleccion"] = cards
        result["seleccion_total"] = round(total, 2)
    elif tool_name == "get_my_cart" and isinstance(result, dict):
        for item in result.get("items") or []:
            cards.append(
                {
                    "id": item.get("producto_id"),
                    "item_id": item.get("id"),
                    "variante_id": item.get("variante_id"),
                    "nombre": item.get("nombre"),
                    "precio": item.get("precio_unitario"),
                    "color": item.get("color"),
                    "talla": item.get("talla"),
                    "imagen": item.get("imagen"),
                    "accion": "QUITAR",
                    "motivo": "En tu carrito actual",
                }
            )
    elif tool_name in {"get_my_orders", "get_my_reservations"} and isinstance(result, list):
        action = "VER_PEDIDO" if tool_name == "get_my_orders" else "VER_RESERVA"
        for item in result[:6]:
            cards.append(
                {
                    "id": item.get("id"),
                    "nombre": f"Pedido #{item.get('id')}" if action == "VER_PEDIDO" else f"Reserva #{item.get('id')}",
                    "precio": item.get("total_bob") or 0,
                    "accion": action,
                    "motivo": item.get("status"),
                    "sku": item.get("code"),
                }
            )
    return cards


async def run_gemma_tool_agent(
    db: Session,
    user: User,
    message: str,
    memory: dict[str, Any],
    complete: CompleteFn,
    emit: EventFn | None = None,
    max_steps: int = 4,
    prompt_factory=prompt_sections,
    delegate: Callable[..., Awaitable[str]] | None = None,
    after_tool: Callable[..., Awaitable[dict | None]] | None = None,
) -> dict[str, Any]:
    """Shared bounded tool loop: the configured planner chooses, services validate."""
    state = read_context(memory)
    catalog = tool_catalog()
    messages = build_messages(prompt_factory(message, state, catalog, []))
    steps: list[dict[str, Any]] = []
    cards: list[dict[str, Any]] = []
    final: dict[str, Any] | None = None

    async def send_event(event: dict[str, Any]) -> None:
        if emit:
            await emit(event)

    protocol_errors = 0
    seen_calls: set[tuple[str, str]] = set()
    planned_calls: list[dict] = []
    for step_index in range(max_steps):
        await send_event(
            {
                "type": "thought",
                "content": (
                    "Altair está interpretando la consulta y eligiendo la siguiente acción..."
                    if step_index == 0
                    else "Altair está revisando la observación antes de decidir cómo continuar..."
                ),
            }
        )
        if step_index == max_steps - 1:
            messages.append(
                {
                    "role": "user",
                    "content": (
                        "ÚLTIMO PASO: no llames más tools. Finaliza usando el JSON finish "
                        "o delega si está permitido. Usa solo las observaciones disponibles."
                    ),
                }
            )
        try:
            agent_thoughts = [
                "Altair sigue procesando tu consulta...",
            ]
            response = None if planned_calls else await _with_keepalive(
                complete(
                    messages,
                    max_tokens=settings.AI_AGENT_MAX_TOKENS,
                    stream=False,
                    response_format=None,
                ),
                emit=emit,
                thoughts=agent_thoughts,
                interval=5.0,
            )
            raw = json.dumps(planned_calls.pop(0)) if planned_calls else response["choices"][0]["message"].get("content") or ""
        except Exception:
            # Propagate to the WebSocket error handler, never report a failed inference as success.
            raise
        decision = _json_decision(raw)
        if decision and decision.get("calls"):
            calls = decision.pop("calls")
            if len(calls) > max_steps - step_index:
                raise ModelRuntimeError("El plan supera el límite de herramientas del turno.")
            continuation = {key: value for key, value in decision.items() if key not in {"tool", "arguments"}}
            planned_calls = [{**continuation, **call, "type": "tool"} for call in calls[1:]]
            decision = {**continuation, **calls[0], "type": "tool"}
        if not decision:
            protocol_errors += 1
            await send_event(
                {
                    "type": "thought",
                    "content": "La acción llegó incompleta; Gemma está corrigiendo su formato sin repetir la consulta...",
                }
            )
            messages.extend(
                [
                    {"role": "assistant", "content": raw[:500]},
                    {"role": "user", "content": "Formato inválido. Devuelve sólo uno de los JSON permitidos."},
                ]
            )
            continue
        if decision.get("type") == "delegate" and delegate is not None:
            state = update_context(state, decision.get("context"))
            observations = [{"tool": step["name"], "args": step["args"], "result": step["result"]} for step in steps]
            await send_event({"type": "progress", "content": "Altair está elaborando la respuesta con los datos consultados."})
            answer = await delegate(message, state, observations)
            final = {**decision, "type": "finish", "answer": answer}
            break
        if decision.get("type") == "finish":
            state = update_context(state, decision.get("context"))
            final = decision
            await send_event(
                {
                    "type": "thought",
                    "content": "Gemma terminó de contrastar los datos y está entregando su respuesta.",
                }
            )
            break

        tool_name = str(decision.get("tool") or "")
        state = update_context(state, decision.get("context"))
        arguments = decision.get("arguments") if isinstance(decision.get("arguments"), dict) else {}
        reason = str(decision.get("reason") or f"Consultando {tool_name}")
        call_key = (
            tool_name,
            json.dumps(arguments, ensure_ascii=False, sort_keys=True, default=str),
        )
        if call_key in seen_calls:
            await send_event(
                {
                    "type": "thought",
                    "content": (
                        "Gemma intentó repetir la misma consulta; el agente conservó la "
                        "observación anterior y le pidió concluir."
                    ),
                }
            )
            messages.extend(
                [
                    {"role": "assistant", "content": json.dumps(decision, ensure_ascii=False)},
                    {
                        "role": "user",
                        "content": (
                            "Esa tool con esos argumentos ya fue ejecutada. No la repitas. "
                            "Responde en Markdown con la observación existente, sin más llamadas."
                        ),
                    },
                ]
            )
            continue
        seen_calls.add(call_key)
        await send_event({"type": "thought", "content": reason})
        await send_event(
            {
                "type": "tool_start",
                "name": tool_name,
                "label": reason[:180],
                "arguments": arguments,
            }
        )
        try:
            result = execute_tool(tool_name, arguments, ToolContext(db=db, user=user))
        except (ValidationError, ValueError) as exc:
            result = {"error": f"Argumentos rechazados: {exc}"}
        steps.append({"name": tool_name, "args": arguments, "result": result, "reason": reason})
        definition = TOOLS.get(tool_name)
        if definition and definition.card_renderer:
            new_cards = definition.card_renderer(ToolContext(db=db, user=user), arguments, result)
        else:
            new_cards = _cards_from_tool(db, tool_name, arguments, result)
        cards.extend(new_cards)
        state = observe_cards(state, cards[:6])
        if new_cards:
            await send_event({"type": "results", "action_items": cards[:8]})
        safe_result = json.loads(json.dumps(result, ensure_ascii=False, default=str))
        await send_event(
            {
                "type": "tool_result",
                "name": tool_name,
                "label": reason[:180],
                "result": safe_result,
            }
        )
        result_count = len(result) if isinstance(result, list) else 1
        if after_tool is not None and not planned_calls:
            observations = [{"tool": step["name"], "args": step["args"], "result": step["result"]} for step in steps]
            final = await after_tool(decision, message, state, observations, cards)
            if final is not None:
                break
        if (decision.get("display") == "cards" and new_cards
                and not planned_calls
                and isinstance(decision.get("intro"), str) and decision["intro"].strip()):
            # Gemma chose a visual answer. Data is rendered from the actual tool result.
            final = {"type": "finish", "answer": decision["intro"].strip()[:350],
                     "presentation": "mixed"}
            break
        await send_event(
            {
                "type": "thought",
                "content": ("La consulta no pudo completarse; Altair está revisando el error."
                            if isinstance(result, dict) and result.get("error")
                            else f"Se recibieron {result_count} resultado(s); Altair los está revisando."),
            }
        )
        observations = [{"tool": step["name"], "args": step["args"], "result": step["result"]} for step in steps]
        messages = build_messages(prompt_factory(message, state, catalog, observations))

    protocol_valid = final is not None
    if final is None:
        raise ModelRuntimeError(
            "Altair alcanzó el límite de pasos sin completar una respuesta válida. "
            "Las consultas ejecutadas aparecen en Acciones; puedes reintentar."
        )

    unique_cards: list[dict[str, Any]] = []
    seen: set[tuple[Any, Any, Any]] = set()
    for card in cards:
        key = (card.get("id"), card.get("variante_id"), card.get("accion"))
        if key not in seen:
            seen.add(key)
            unique_cards.append(card)

    outfit_step = next((step for step in steps if step["name"] == "recommend_outfit"), None)
    notices = []

    response_meta: dict[str, Any] = {
        "kind": "agent",
        "agent_mode": "gemma_observe_act",
        "agent_protocol_valid": protocol_valid,
    }
    if (outfit_step and isinstance(outfit_step["result"], dict)
            and outfit_step["result"].get("status") != "needs_input"):
        result = outfit_step["result"]
        notices.extend([
            {"type": "warning", "title": "Prenda no encontrada", "message": value}
            for value in result.get("restricciones_sin_stock") or []
        ])
        response_meta = {
            "kind": "outfit",
            "agent_mode": "gemma_observe_act",
            "total_bob": result.get("seleccion_total"),
            "budget_bob": outfit_step["args"].get("max_budget"),
            "item_count": len(unique_cards),
            "occasion": outfit_step["args"].get("occasion") or "personalizada",
            "can_add_all": bool(unique_cards),
            "replaces_cart": True,
            "agent_protocol_valid": protocol_valid,
        }

    presentation = str(final.get("presentation") or ("mixed" if unique_cards else "text"))
    state = observe_cards(state, unique_cards[:6])
    if final.get("ui") == "product_picker":
        response_meta["product_picker"] = [
            item.model_dump() for item in state.recent if item.type == "product"
        ]
    return {
        "tool_name": None,
        "tool_args": {"steps": len(steps)},
        "tool_result": {"steps": steps},
        "composite_sub_tools": steps,
        "action_items": unique_cards[:8],
        "requires_llm": False,
        "direct_response": str(final.get("answer") or "").strip(),
        "fallback_response": str(final.get("answer") or "").strip(),
        "presentation_mode": presentation,
        "response_title": str(final.get("title") or "Resultado verificado"),
        "notices": notices,
        "response_meta": response_meta,
        "suggested_actions": [
            {"label": item["label"].strip()[:60], "prompt": item["prompt"].strip()[:300]}
            for item in (final.get("suggested_actions") or [])[:3]
            if isinstance(item, dict) and isinstance(item.get("label"), str)
            and isinstance(item.get("prompt"), str) and item["label"].strip() and item["prompt"].strip()
        ] if isinstance(final.get("suggested_actions", []), list) else [],
        "chat_context": state.model_dump(),
        "memory_updates": {},
        "events_emitted": emit is not None,
    }
