"""Commercial facts are rendered by the server, never copied from model prose."""

import re
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ProductReply(BaseModel):
    model_config = ConfigDict(extra="forbid")
    product_ids: list[int] = Field(min_length=1, max_length=6)
    presentation: Literal["text", "cards"] = "text"
    include_stock: bool = False


class QueryPresentation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    presentation: Literal["text", "cards", "continue"] = "continue"
    include_stock: bool = False


class StoreDataReply(BaseModel):
    model_config = ConfigDict(extra="forbid")
    presentation: Literal["auto", "text"] = "auto"
    source_tool: Literal[
        "get_my_shopping_context",
        "discover_for_me",
        "recommend_pickup_branches",
        "plan_more_for_less",
        "find_cart_savings",
        "get_branch_availability",
        "get_stock",
        "calculate_cart_totals",
        "calculate_selection_budget",
        "compare_products",
        "get_my_orders",
        "get_my_reservations",
        "get_my_payment_status",
        "get_store_policy",
    ]


def render_store_data(tool: str, data) -> str:
    """Small server-owned templates for non-catalog commerce capabilities."""
    if tool in {
        "get_my_shopping_context",
        "discover_for_me",
        "recommend_pickup_branches",
        "plan_more_for_less",
        "find_cart_savings",
    }:
        from app.services.personal_shopping import render_shopping_data

        return render_shopping_data(tool, data)
    money = lambda value: f"Bs {Decimal(str(value)):,.2f}"
    if tool == "get_branch_availability":
        return (
            "\n".join(
                f"- **{r['sucursal']}** · {r['direccion']} · {r['color']}, talla {r['talla']}: {r['disponible']} unidades"
                for r in data
            )
            or "No hay disponibilidad registrada en sucursales para esa variante."
        )
    if tool == "get_stock":
        return (
            "\n".join(
                f"- **{r['product']}** · {r['color']}, talla {r['size']}: {r['available']} unidades disponibles"
                for r in data
            )
            or "No encontré stock registrado para esa prenda."
        )
    if tool == "calculate_cart_totals":
        lines = [
            f"- {r['name']} · {r['quantity']} × {money(r['unit_price_bob'])} = {money(r['line_total_bob'])}"
            for r in data["lines"]
        ]
        return (
            "Precios registrados en tu carrito:\n"
            + "\n".join(lines)
            + f"\n\n**Subtotal: {money(data['subtotal_bob'])}** · {data['unit_count']} prendas. El total de compra se confirma en caja."
        )
    if tool == "calculate_selection_budget":
        return (
            f"**Total de la selección: {money(data['total'])}**\n\nPresupuesto: {money(data['presupuesto'])} · Saldo: {money(data['saldo'])}.\n\n"
            + (
                "Las variantes tienen stock registrado."
                if data["stock_verificado"]
                else "Hay variantes sin stock disponible."
            )
        )
    if tool == "compare_products":
        return "Comparación del catálogo:\n" + "\n".join(
            f"- **{r['name']}**: {money(r['price_bob'])} · Nivel de calidad registrado: {r['quality_level']}"
            for r in data["ranking"]
        )
    if tool == "get_my_orders":
        return (
            "\n".join(
                f"- **Pedido #{r['id']}** · {r['status']} · {money(r['total_bob'])} · {r['created_at']}"
                for r in data
            )
            or "No tienes pedidos registrados."
        )
    if tool == "get_my_reservations":
        return (
            "\n".join(
                f"- **Reserva #{r['id']}** · {r['status']} · Vence: {r['expires_at']}"
                for r in data
            )
            or "No tienes reservas registradas."
        )
    if tool == "get_my_payment_status":
        return (
            f"**Pedido #{data['pedido_id']}** · {data['estado_pedido']} · {money(data['total'])}\n\n"
            + "\n".join(
                f"- {p['metodo']}: {p['estado']} · {money(p['monto'])}"
                for p in data["pagos"]
            )
            + "\n\nEstado registrado en la tienda; no confirma movimientos bancarios."
        )
    if tool == "get_store_policy":
        return (
            str(data["policy"])
            if data.get("configured")
            else "La tienda todavía no configuró esa política. Consulta con atención al cliente."
        )
    raise ValueError("Fuente de datos no soportada")


def has_commercial_claim(text: str) -> bool:
    """Output gate, not user-intent routing. Reject unverifiable numeric/location claims."""
    return bool(
        re.search(
            r"(?:\$\s*(?:usd\s*)?|\b(?:bs\.?|bob|usd|bolivianos?|d[oó]lares?)\s*)\d"
            r"|\d[\d.,]*\s*(?:\$|bs\b|bob\b|usd\b|bolivianos?\b|d[oó]lares?\b|unidades?\b)"
            r"|\b(?:precio|stock|existencias?)\s*[:=]?\s*\d"
            r"|\bdisponible[s]?\s+en\s+(?:la\s+|el\s+)?(?:sucursal|tienda|showroom)"
            r"|\b(?:stock|existencias?)\s*:\s*(?:disponible|agotado)",
            text,
            re.I,
        )
    )


def render_products(
    cards: list[dict], *, include_stock: bool = False, branches=()
) -> str:
    lines = ["Estas son las prendas verificadas en el catálogo:"]
    for card in cards:
        price = Decimal(str(card["precio"]))
        variant = " · ".join(
            str(part)
            for part in (
                card.get("color"),
                f"Talla {card['talla']}" if card.get("talla") else None,
            )
            if part
        )
        line = f"- **{card['nombre']}** — **Bs {price:,.2f}**"
        if variant:
            line += f" · {variant}"
        if include_stock and card.get("stock_disponible") is not None:
            line += (
                f" · {card['stock_disponible']} unidades disponibles de esta variante"
            )
        lines.append(line)
        if include_stock:
            for observation in branches:
                if observation["args"].get("product_id") != card["id"]:
                    continue
                for row in observation["result"]:
                    if row.get("variante_id") == card.get("variante_id"):
                        lines.append(
                            f"  - {row['sucursal']}: {row['disponible']} unidades · {row['direccion']}"
                        )
    lines.append(
        "\nPrecios en bolivianos. La disponibilidad se vuelve a comprobar al comprar."
    )
    return "\n".join(lines)
