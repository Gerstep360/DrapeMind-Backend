import json
import re
from typing import Any, Awaitable, Callable

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.models import User
from app.services.ai_tools import ToolContext, execute_tool, tool_catalog
from app.services.store import get_product_detail


CompleteFn = Callable[..., Awaitable[dict[str, Any]]]
EventFn = Callable[[dict[str, Any]], Awaitable[None]]


def _json_decision(raw: str) -> dict[str, Any] | None:
    raw = raw.strip().removeprefix("```json").removesuffix("```").strip()
    try:
        value = json.loads(raw)
        return value if isinstance(value, dict) else None
    except json.JSONDecodeError:
        matches = re.findall(r"\{.*?\}", raw, re.DOTALL)
        for candidate in reversed(matches):
            try:
                value = json.loads(candidate)
                if isinstance(value, dict):
                    return value
            except json.JSONDecodeError:
                continue
    # Si Gemma respondió en prosa natural sin envolver en JSON:
    if len(raw) > 10 and not raw.startswith("{"):
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
) -> dict[str, Any]:
    """Bounded Observe/Think/Act loop. Gemma chooses every tool; FastAPI only validates it."""
    compact_tools = []
    for tool in tool_catalog():
        schema = tool["parameters"]
        compact_tools.append(
            {
                "name": tool["name"],
                "use": tool["description"],
                "arguments": {
                    name: {
                        key: value[key]
                        for key in ("type", "default", "minimum", "maximum")
                        if key in value
                    }
                    for name, value in (schema.get("properties") or {}).items()
                },
                "required": schema.get("required") or [],
            }
        )
    system = (
        "Eres Altair en modo AGENTE. Tú decides qué herramientas usar y en qué orden. "
        "FastAPI sólo valida permisos, argumentos, stock, precios y cálculos. Interpreta significado, "
        "hipérbole, ironía y contexto; no clasifiques por palabras aisladas. Distingue con precisión "
        "entre una prenda individual, varias opciones, un outfit y datos de la cuenta. "
        "No saludes: la interfaz ya dio la bienvenida al abrir el chat. Nunca inventes productos, tallas, "
        "precios ni resultados. Respeta tallas exactas y alternativas explícitas.\n"
        "Responde EXCLUSIVAMENTE JSON con uno de estos formatos:\n"
        "{\"type\":\"tool\",\"tool\":\"nombre\",\"arguments\":{},\"reason\":\"acción breve\"}\n"
        "{\"type\":\"finish\",\"answer\":\"asesoría elocuente, argumentada y personalizada basada en los resultados verificados del atelier\",\"title\":\"título elegante\",\"presentation\":\"text|cards|mixed\"}"
    )
    messages: list[dict[str, str]] = [
        {"role": "system", "content": system},
        {
            "role": "user",
            "content": (
                f"CONSULTA: {message}\n"
                f"MEMORIA VERIFICADA: {json.dumps(memory, ensure_ascii=False)}\n"
                f"TOOLS: {json.dumps(compact_tools, ensure_ascii=False)}"
            ),
        },
    ]
    steps: list[dict[str, Any]] = []
    cards: list[dict[str, Any]] = []
    final: dict[str, Any] | None = None

    async def send_event(event: dict[str, Any]) -> None:
        if emit:
            await emit(event)

    protocol_errors = 0
    seen_calls: set[tuple[str, str]] = set()
    for step_index in range(max_steps):
        await send_event(
            {
                "type": "thought",
                "content": (
                    "Gemma está interpretando la consulta y eligiendo la siguiente acción..."
                    if step_index == 0
                    else "Gemma está revisando la observación antes de decidir cómo continuar..."
                ),
            }
        )
        if step_index == max_steps - 1:
            messages.append(
                {
                    "role": "user",
                    "content": (
                        "ÚLTIMO PASO: no llames más tools. Responde type=finish usando sólo "
                        "las observaciones verificadas, incluso si el resultado está vacío."
                    ),
                }
            )
        try:
            response = await complete(
                messages,
                max_tokens=1024,
                stream=False,
                response_format={"type": "json_object"},
            )
            raw = response["choices"][0]["message"].get("content") or ""
        except Exception:
            await send_event(
                {
                    "type": "thought",
                    "content": "Gemma sintetizó la información y procede a estructurar la respuesta...",
                }
            )
            break
        decision = _json_decision(raw)
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
        if decision.get("type") == "finish":
            final = decision
            await send_event(
                {
                    "type": "thought",
                    "content": "Gemma terminó de contrastar los datos y está entregando su respuesta.",
                }
            )
            break

        tool_name = str(decision.get("tool") or "")
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
                            "Responde type=finish con la observación existente."
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
                "arguments": arguments,
            }
        )
        try:
            result = execute_tool(tool_name, arguments, ToolContext(db=db, user=user))
        except (ValidationError, ValueError) as exc:
            result = {"error": f"Argumentos rechazados: {exc}"}
        steps.append({"name": tool_name, "args": arguments, "result": result, "reason": reason})
        cards.extend(_cards_from_tool(db, tool_name, arguments, result))
        safe_result = json.loads(json.dumps(result, ensure_ascii=False, default=str))
        await send_event(
            {
                "type": "tool_result",
                "name": tool_name,
                "result": safe_result,
            }
        )
        result_count = len(result) if isinstance(result, list) else 1
        await send_event(
            {
                "type": "thought",
                "content": f"FastAPI devolvió {result_count} resultado(s) verificado(s); Gemma los está evaluando.",
            }
        )
        observation = json.dumps(result, ensure_ascii=False, default=str)
        messages.extend(
            [
                {"role": "assistant", "content": json.dumps(decision, ensure_ascii=False)},
                {
                    "role": "user",
                    "content": (
                        f"OBSERVACIÓN VERIFICADA DE {tool_name}: {observation[:6500]}\n"
                        "Un resultado vacío también es una respuesta válida. Si esto responde "
                        "la consulta, finaliza ahora; no repitas la misma tool."
                    ),
                },
            ]
        )

    protocol_valid = final is not None
    if final is None:
        if cards:
            names = ", ".join(str(card.get("nombre") or "prenda") for card in cards[:3])
            fallback_answer = (
                f"He evaluado tu solicitud y contrastado la disponibilidad en showroom. "
                f"A continuación te presento las piezas seleccionadas ({names}) con stock, tallas y acabados sastreros confirmados."
            )
        elif steps and isinstance(steps[-1].get("result"), list) and not steps[-1]["result"]:
            fallback_answer = (
                "He consultado el catálogo del atelier, pero no encontré piezas disponibles con esos filtros exactos."
            )
        else:
            fallback_answer = (
                "He analizado tu consulta. Puedes explorar las opciones curadas en el catálogo o indicarme una ocasión para diseñar un look a medida."
            )
        final = {
            "answer": fallback_answer,
            "title": "Asesoría DrapeMind Atelier",
            "presentation": "mixed" if cards else "text",
        }

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
    if outfit_step and isinstance(outfit_step["result"], dict):
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
        "suggested_actions": [],
        "memory_updates": {},
        "events_emitted": emit is not None,
    }
