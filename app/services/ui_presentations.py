"""Prefabricated chat views populated exclusively from authorized tool observations."""

from decimal import Decimal


def _text(value):
    return str(value if value is not None else "—")[:1000]


def _money(value):
    return f"Bs {Decimal(str(value)):,.2f}"


def tool_presentation(name: str, data) -> dict | None:
    if isinstance(data, dict) and data.get("error"):
        return None
    if name == "get_my_shopping_context":
        profile = data["profile"]
        labels = {
            "genero": "Género",
            "talla_superior": "Talla superior",
            "talla_inferior": "Talla inferior",
            "talla_calzado": "Calzado",
            "estilos_preferidos": "Estilos",
            "colores_favoritos": "Colores",
            "ocasiones_frecuentes": "Ocasiones",
            "presupuesto_habitual": "Presupuesto habitual",
            "silueta_preferida": "Silueta",
        }
        lines = [
            f"{labels[k]}: {', '.join(v) if isinstance(v, list) else v}"
            for k, v in profile.items()
            if v
        ]
        return {
            "type": "information",
            "title": "Tus preferencias de compra",
            "source_tool": name,
            "body": "\n".join(
                lines + ([f"Ciudad: {data['city']}"] if data["city"] else [])
            )
            or "Todavía no tienes preferencias guardadas.",
            "tone": "neutral",
            "note": "Lo que indiques en el chat tiene prioridad. Buscar no modifica tu perfil.",
        }
    if name == "recommend_pickup_branches":
        return {
            "type": "branch_options",
            "title": "Dónde reunir tu selección",
            "source_tool": name,
            "city": data["city"] or "Ciudad sin confirmar",
            "items": [
                {
                    "id": r["id"],
                    "name": _text(r["name"]),
                    "city": _text(r["city"]),
                    "address": _text(r["address"]),
                    "coverage": f"{r['covered']} de {r['requested']} variantes",
                    "complete": r["complete"],
                    "same_city": r["same_city"],
                }
                for r in data["branches"]
            ],
            "note": data["note"],
        }
    if name in {"discover_for_me", "plan_more_for_less", "find_cart_savings"}:
        metrics, items = [], []
        if name == "discover_for_me":
            title = (
                "Novedades para tus gustos"
                if data.get("recent_days")
                else "Elegidas con tus preferencias"
            )
            items = [
                {
                    "label": p["nombre"],
                    "detail": " · ".join(p["reasons"]),
                    "badge": ('Nuevo · ' if p.get('is_recent') else '') + f"Talla {p['talla']}",
                }
                for p in data["products"]
            ]
        elif name == "plan_more_for_less":
            title = "Más prendas dentro de tu presupuesto"
            metrics = [
                {"label": "Prendas", "value": str(data["item_count"])},
                {"label": "Total", "value": _money(data["total"])},
                {"label": "Saldo disponible", "value": _money(data["remaining"])},
            ]
            items = [
                {
                    "label": "Tu límite",
                    "detail": _money(data["budget"]),
                    "badge": "Presupuesto",
                }
            ]
        else:
            title = "Ahorro posible en tu carrito"
            metrics = [
                {"label": "Carrito actual", "value": _money(data["before"])},
                {"label": "Con alternativas", "value": _money(data["after"])},
                {"label": "Ahorro por cambios", "value": _money(data["saving"])},
            ]
            items = [
                {
                    "label": f"{c['quantity']} × {c['from']} → {c['to']}",
                    "detail": c["detail"],
                    "badge": _money(c["saving"]),
                }
                for c in data["changes"]
            ]
            if not items:
                items = [
                    {
                        "label": "Conserva tu selección",
                        "detail": "No encontré alternativas más baratas que cumplan esos criterios.",
                        "badge": "Sin cambios",
                    }
                ]
            if data["extras"]:
                items.append(
                    {
                        "label": f"Puedes añadir {len(data['extras'])} prenda(s)",
                        "detail": f"{', '.join(p['nombre'] for p in data['extras'])}. Total con extras: {_money(data['total_with_extras'])}; queda {_money(data['remaining'])} frente al carrito actual.",
                        "badge": "Con tu ahorro",
                    }
                )
        note = data["note"]
        if data.get("truncated"):
            note += " Consulta limitada a 2000 variantes; puedes afinar los filtros."
        if data.get("missing_sizes"):
            note += (
                " Falta confirmar talla para: " + ", ".join(data["missing_sizes"]) + "."
            )
        if not data.get("products") and name != "find_cart_savings":
            items.append(
                {
                    "label": "Sin coincidencias",
                    "detail": "No hay prendas disponibles con esos criterios. Puedes cambiar un filtro; no cambié tu talla.",
                    "badge": "Catálogo consultado",
                }
            )
        return {
            "type": "shopping_summary",
            "title": title,
            "source_tool": name,
            "criteria": data.get("criteria", []),
            "metrics": metrics,
            "items": items[:12],
            "note": note,
        }
    if name == "compare_products":
        rows = [
            {
                "name": _text(r["name"]),
                "price": _money(r["price_bob"]),
                "quality": _text(r["quality_level"]),
            }
            for r in data["ranking"][:20]
        ]
        return {
            "type": "data_table",
            "title": "Compara las prendas",
            "source_tool": name,
            "columns": [
                {"key": "name", "label": "Prenda"},
                {"key": "price", "label": "Precio"},
                {"key": "quality", "label": "Calidad registrada"},
            ],
            "rows": rows,
            "empty_message": "No hay prendas verificadas para comparar.",
        }
    if name in {"get_stock", "get_branch_availability"}:
        branch = name == "get_branch_availability"
        rows = [
            {
                "name": _text(r["sucursal"] if branch else r["product"]),
                "variant": _text(
                    f"{r.get('color') or 'Sin color registrado'} · Talla {r['talla'] if branch else r['size']}"
                ),
                "available": _text(r["disponible"] if branch else r["available"]),
                "location": _text(r.get("direccion", "")),
            }
            for r in data[:20]
        ]
        return {
            "type": "data_table",
            "title": "Disponibilidad en tiendas" if branch else "Tallas y existencias",
            "source_tool": name,
            "columns": [
                {"key": "name", "label": "Tienda" if branch else "Prenda"},
                {"key": "variant", "label": "Variante"},
                {"key": "available", "label": "Unidades disponibles"},
            ]
            + ([{"key": "location", "label": "Dirección"}] if branch else []),
            "rows": rows,
            "empty_message": "No hay existencias registradas para estos criterios.",
            "note": f"Mostrando {min(len(data), 20)} de {len(data)} variantes consultadas.",
        }
    if name in {"calculate_selection_budget", "calculate_cart_totals"}:
        budget = name == "calculate_selection_budget"
        metrics = (
            [
                {"label": "Total de la selección", "value": _money(data["total"])},
                {"label": "Tu presupuesto", "value": _money(data["presupuesto"])},
                {"label": "Saldo", "value": _money(data["saldo"])},
            ]
            if budget
            else [
                {
                    "label": "Subtotal del carrito",
                    "value": _money(data["subtotal_bob"]),
                },
                {"label": "Prendas", "value": _text(data["unit_count"])},
            ]
        )
        lines = (
            []
            if budget
            else [
                {
                    "label": _text(r["name"]),
                    "value": f"{r['quantity']} × {_money(r['unit_price_bob'])} = {_money(r['line_total_bob'])}",
                }
                for r in data["lines"][:20]
            ]
        )
        return {
            "type": "metrics",
            "title": "Tu presupuesto" if budget else "Tu carrito, en números",
            "source_tool": name,
            "metrics": metrics,
            "lines": lines,
            "note": (
                "Stock disponible verificado."
                if data["stock_verificado"]
                else "Hay variantes sin stock disponible."
            )
            if budget
            else "Precios registrados en el carrito. El total de compra se confirma al finalizar.",
        }
    if name in {"get_my_orders", "get_my_reservations", "get_my_payment_status"}:
        payment = name == "get_my_payment_status"
        orders = name == "get_my_orders"
        items = (
            [
                {
                    "label": f"Pedido #{data['pedido_id']}",
                    "status": _text(data["estado_pedido"]),
                    "detail": _money(data["total"]),
                }
            ]
            + [
                {
                    "label": _text(r["metodo"]),
                    "status": _text(r["estado"]),
                    "detail": _money(r["monto"]),
                }
                for r in data["pagos"][:10]
            ]
            if payment
            else [
                {
                    "label": f"{'Pedido' if orders else 'Reserva'} #{r['id']}",
                    "status": _text(r["status"]),
                    "detail": f"{_money(r['total_bob'])} · {r['created_at']}"
                    if orders
                    else f"Vence: {r['expires_at']}",
                }
                for r in data[:20]
            ]
        )
        return {
            "type": "status_list",
            "title": "Estado de tu pago"
            if payment
            else ("Tus pedidos" if orders else "Tus reservas"),
            "source_tool": name,
            "items": items,
            "route": "/orders" if payment or orders else "/reservations",
            "empty_message": "No tienes registros para esta consulta.",
            "note": "Estado registrado en la tienda; no confirma movimientos bancarios."
            if payment
            else "",
        }
    if name == "get_store_policy":
        topics = {
            "shipping": "Envíos",
            "returns": "Cambios y devoluciones",
            "payments": "Formas de pago",
            "hours": "Horarios",
        }
        return {
            "type": "information",
            "title": topics.get(data.get("topic"), "Información de la tienda"),
            "source_tool": name,
            "body": _text(data.get("policy"))
            if data.get("configured")
            else "La tienda todavía no configuró esta información. Consulta con atención al cliente.",
            "tone": "neutral" if data.get("configured") else "notice",
        }
    return None
