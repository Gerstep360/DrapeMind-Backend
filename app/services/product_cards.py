"""Server-owned cards built from authorized catalog observations."""

from typing import Any
from fastapi import HTTPException
from sqlalchemy.orm import Session
from app.services.store import get_product_detail


def _available_variant(
    detail: dict[str, Any], requested_size: str | None
) -> dict[str, Any] | None:
    variants = [
        variant for variant in detail.get("variantes") or [] if variant.get("activo")
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
    return next(
        (variant for variant in variants if (variant.get("stock_disponible") or 0) > 0),
        variants[0] if variants else None,
    )


def _product_card(
    db: Session,
    product: dict[str, Any],
    requested_size: str | None = None,
) -> dict[str, Any] | None:
    product_id = (
        product.get("id") or product.get("producto_id") or product.get("product_id")
    )
    if not product_id:
        return None
    try:
        detail = get_product_detail(db, int(product_id), fresh=True)
    except HTTPException as exc:
        if exc.status_code == 404:
            return None
        raise
    variant_id = product.get("variante_id") or product.get("variant_id")
    variant = (
        next(
            (
                v
                for v in detail.get("variantes", [])
                if v["id"] == variant_id and v.get("activo")
            ),
            None,
        )
        if variant_id
        else _available_variant(detail, requested_size)
    )
    if not variant:
        return None
    return {
        "id": int(product_id),
        "variante_id": variant.get("id"),
        "nombre": detail["nombre"],
        "precio": float(detail["precio"]),
        "color": variant.get("color"),
        "talla": variant.get("talla"),
        "sku": variant.get("sku"),
        "stock_disponible": variant.get("stock_disponible", 0),
        "imagen": variant.get("imagen") or ((detail.get("imagenes") or [None])[0]),
        "accion": "AGREGAR",
        "motivo": "Variante consultada en el catálogo",
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
        "discover_for_me",
        "plan_more_for_less",
        "find_cart_savings",
    } and isinstance(result, dict):
        for product in (result.get("extras", []) + result.get("products", []))[:6]:
            card = _product_card(db, product, product.get("talla"))
            if card:
                card["motivo"] = str(product.get("motivo") or "")[:300]
                cards.append(card)
    elif tool_name in {
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
        if "seleccion" in result and isinstance(result["seleccion"], list):
            cards.extend(result["seleccion"])
        else:
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
                if (
                    budget is not None
                    and len(cards) >= 3
                    and total + price > float(budget)
                ):
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
                        "motivo": "Seleccionado para tu look",
                    }
                )
            result["seleccion"] = cards
            result["seleccion_total"] = round(total, 2)
    elif tool_name == "get_my_cart" and isinstance(result, dict):
        cart_items = result.get("items") or []
        for item in cart_items:
            cards.append(
                {
                    "id": item.get("producto_id"),
                    "item_id": item.get("id"),
                    "variante_id": item.get("variante_id"),
                    "nombre": item.get("nombre"),
                    "precio": float(
                        item.get("precio_unitario") or item.get("precio") or 0
                    ),
                    "color": item.get("color"),
                    "talla": item.get("talla"),
                    "imagen": item.get("imagen"),
                    "accion": "QUITAR",
                    "motivo": "En tu carrito",
                }
            )
        for sug in result.get("sugerencias") or []:
            cards.append(
                {
                    "id": sug.get("producto_id") or sug.get("id"),
                    "variante_id": sug.get("variante_id"),
                    "nombre": sug.get("nombre"),
                    "precio": float(sug.get("precio") or 0),
                    "color": sug.get("color"),
                    "talla": sug.get("talla"),
                    "imagen": sug.get("imagen"),
                    "accion": "AGREGAR",
                    "motivo": "Sugerencia para combinar tu estilo",
                }
            )
    elif tool_name in {"get_my_orders", "get_my_reservations"} and isinstance(
        result, list
    ):
        action = "VER_PEDIDO" if tool_name == "get_my_orders" else "VER_RESERVA"
        for item in result[:6]:
            cards.append(
                {
                    "id": item.get("id"),
                    "nombre": f"Pedido #{item.get('id')}"
                    if action == "VER_PEDIDO"
                    else f"Reserva #{item.get('id')}",
                    "precio": item.get("total_bob") or 0,
                    "accion": action,
                    "motivo": item.get("status"),
                    "sku": item.get("code"),
                }
            )
    return cards
