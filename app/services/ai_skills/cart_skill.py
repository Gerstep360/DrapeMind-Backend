from typing import Any
from sqlalchemy.orm import Session
from app.models import User
from app.services.ai_skills.base_skill import BaseAiSkill
from app.services.ai_tools import ToolContext, execute_tool
from app.services.store import get_product_detail


class CartSkill(BaseAiSkill):
    """Maneja el análisis, calificación detallada de estilo (1 al 10), equilibrio de prendas y optimización del perchero del usuario."""

    name: str = "cart_skill"
    description: str = "Inspección, calificación profunda de estilo (1 al 10), armonía de telas y sugerencias de combinación de la bolsa de compras."

    def can_handle(self, message: str, context: dict[str, Any]) -> bool:
        clean = message.lower()
        return any(k in clean for k in ["carrito", "perchero", "bolsa", "guardado", "mi lista", "califica", "evalua", "1 al 10", "1 a 10", "equilibrad", "que tengo", "qué tengo"])

    def execute(self, db: Session, user: User, message: str, context: dict[str, Any]) -> dict[str, Any]:
        tool_ctx = ToolContext(db=db, user=user)
        tool_res = execute_tool("get_my_cart", {}, tool_ctx)
        action_items = []
        cart_product_ids = set()
        items_detail = []
        total_subtotal = 0.0

        # 1. Extraer prendas actuales en el carrito (Acción: QUITAR)
        if isinstance(tool_res, dict) and tool_res.get("items"):
            for it in tool_res["items"]:
                pid = it.get("producto_id")
                if pid:
                    cart_product_ids.add(pid)
                p_subtotal = float(it.get("subtotal") or (float(it.get("precio_unitario") or 0) * int(it.get("cantidad") or 1)))
                total_subtotal += p_subtotal

                item_info = {
                    "id": pid,
                    "variante_id": it.get("variante_id"),
                    "item_id": it.get("id"),
                    "nombre": it.get("nombre") or "Prenda Atelier",
                    "color": it.get("color") or "Tono Único",
                    "talla": it.get("talla") or "Única",
                    "cantidad": it.get("cantidad") or 1,
                    "precio": float(it.get("precio_unitario") or 0),
                    "subtotal": p_subtotal,
                    "imagen": it.get("imagen"),
                    "accion": "QUITAR",
                    "motivo": "En tu perchero actual",
                }
                action_items.append(item_info)
                items_detail.append(item_info)

        has_items = bool(action_items)
        complements = []

        # 2. Buscar complementos sugeridos de alta calidad si hay prendas
        if has_items:
            trending = execute_tool("get_trending_pieces", {"limit": 6}, tool_ctx)
            if isinstance(trending, list):
                for p in trending:
                    if p.get("id") in cart_product_ids:
                        continue
                    detail = get_product_detail(db, p["id"])
                    variant = next(
                        (v for v in detail.get("variantes", []) if v.get("activo") and (v.get("stock_disponible") or 0) > 0),
                        None,
                    )
                    if not variant:
                        continue
                    comp_item = {
                        "id": p.get("id"),
                        "variante_id": variant.get("id"),
                        "nombre": p.get("nombre"),
                        "color": variant.get("color"),
                        "talla": variant.get("talla"),
                        "sku": variant.get("sku"),
                        "precio": float(p.get("precio") or 0),
                        "imagen": variant.get("imagen") or ((p.get("imagenes") or [None])[0]),
                        "accion": "AGREGAR",
                        "motivo": f"Complemento sugerido · Calidad Q{p.get('calidad_nivel') or 4}",
                    }
                    action_items.append(comp_item)
                    complements.append({
                        "nombre": p.get("nombre"),
                        "precio": p.get("precio"),
                        "calidad": p.get("calidad_nivel"),
                        "color": variant.get("color"),
                        "talla": variant.get("talla"),
                    })
                    if len(complements) >= 2:
                        break

            if isinstance(tool_res, dict):
                tool_res["sugerencias_complemento"] = complements

        # 3. Análisis estilístico dinámico y cálculo de puntuación personalizado
        raw_name = getattr(user, "nombre", None)
        user_name = raw_name.split()[0] if raw_name else "estimado cliente"

        suggested_actions = []

        if has_items:
            # Categorización precisa de las prendas
            top_items = []
            bottom_items = []
            outerwear_acc_items = []
            shoe_items = []

            for it in items_detail:
                n = it["nombre"].lower()
                if any(k in n for k in ["polera", "camisa", "blusa", "polo", "top"]):
                    top_items.append(it)
                elif any(k in n for k in ["pantalon", "pantalón", "jean", "falda", "palazzo", "bermuda"]):
                    bottom_items.append(it)
                elif any(k in n for k in ["zapato", "calzado", "mocas", "zapatilla", "bota"]):
                    shoe_items.append(it)
                else:
                    outerwear_acc_items.append(it)

            # Cálculo de puntuación dinámica
            base_score = 6.5
            if top_items and bottom_items:
                base_score += 2.0
            elif top_items or bottom_items:
                base_score += 0.8
            if outerwear_acc_items:
                base_score += 0.7
            if shoe_items:
                base_score += 0.5
            if len(items_detail) >= 3:
                base_score += 0.3
            # Penalizar exceso de prendas redundantes
            if len(top_items) >= 3 and not bottom_items:
                base_score -= 1.0

            score = max(5.0, min(9.7, base_score))

            first_item = items_detail[0]["nombre"]
            first_color = items_detail[0]["color"]

            critique_lines = [
                f"Saludos, {user_name}. He realizado una evaluación estilística de las {len(items_detail)} prendas en tu perchero (Calificación del perchero: {score:.1f} / 10).",
            ]

            if top_items and bottom_items:
                critique_lines.append(
                    f"Cuentas con un balance óptimo entre {len(top_items)} prenda(s) superior(es) y {len(bottom_items)} prenda(s) inferior(es), permitiendo una estructura visual armónica y variada."
                )
            elif top_items and not bottom_items:
                critique_lines.append(
                    f"Tu selección cuenta con {len(top_items)} parte(s) superior(es) de gran presencia, pero te recomiendo incorporar una pieza inferior sastrera o palazzo para cerrar el conjunto."
                )
            elif bottom_items and not top_items:
                critique_lines.append(
                    f"Tienes {len(bottom_items)} parte(s) inferior(es) sin tops coordinados. Sugiero sumar una camisa de lino o blusa de seda para balancear el look."
                )
            else:
                critique_lines.append(
                    "Tu selección presenta piezas individuales interesantes. Unificar la base con prendas estructurales maximizará su versatilidad."
                )

            critique_lines.append(
                f"La inversión total acumulada es de Bs {total_subtotal:.2f}. "
                f"El diálogo entre los tonos ({first_color}) y las caídas textiles aporta una presencia editorial sobria y sofisticada."
            )

            if complements:
                comp_names = " y ".join(c["nombre"] for c in complements)
                critique_lines.append(
                    f"Para potenciar este look, he seleccionado {comp_names} como complementos que puedes explorar y probarte a continuación."
                )

            fallback_text = "\n\n".join(critique_lines)

            if not bottom_items:
                suggested_actions.append({
                    "label": "Sumar pantalón a juego",
                    "prompt": f"Recomiéndame un pantalón o prenda inferior para combinar con {first_item}",
                })
            if not shoe_items:
                suggested_actions.append({
                    "label": "Ver calzado coordinado",
                    "prompt": f"Qué calzado del atelier combina con las prendas en tono {first_color} de mi carrito?",
                })
            if total_subtotal > 600:
                suggested_actions.append({
                    "label": "Reducir costo sin perder estilo",
                    "prompt": "Cómo optimizar mi carrito para reducir el total manteniendo alta calidad?",
                })
            suggested_actions.extend([
                {
                    "label": "Sugerir abrigo o chaqueta",
                    "prompt": "Recomiéndame una chaqueta o abrigo para combinar con mi selección actual",
                },
                {
                    "label": "Cómo llevarlo a 10/10",
                    "prompt": "Qué prenda específica le falta a mi carrito para tener una calificación perfecta de 10/10?",
                },
            ])

        else:
            fallback_text = (
                f"Saludos, {user_name}. Tu perchero se encuentra actualmente vacío.\n\n"
                "Para realizar una asesoría y calificación estilística de 1 al 10, puedes explorar el showroom o indicarme una ocasión para diseñar un outfit a medida."
            )
            suggested_actions = [
                {"label": "👔 Armar outfit para cena", "prompt": "Arma un outfit elegante para una cena con presupuesto de Bs 700"},
                {"label": "⚖️ Optimizar outfit y calidad", "prompt": "Optimiza mi outfit para gastar bien en ropa que dure"},
                {"label": "✨ Piezas exclusivas del atelier", "prompt": "Muéstrame las piezas más exclusivas y de tendencia del showroom"},
            ]

        return {
            "tool_name": "get_my_cart",
            "tool_args": {},
            "tool_result": tool_res,
            "action_items": action_items[:6],
            "requires_llm": True,
            "direct_response": None,
            "fallback_response": fallback_text,
            "focus_prompt": (
                f"Ofrece una calificación y crítica editorial completa del perchero del cliente {user_name}. "
                "1. Entrega una Calificación explícita de 1 al 10 (ej. Calificación del Perchero: 8.5 / 10). "
                "2. Evalúa equilibrio de siluetas (tops vs bottoms), armonía de colores y telas. "
                f"3. Cita el total de Bs {total_subtotal:.2f}. "
                "4. Explica qué quitar si hay redundancias y qué complementos agregar de las tarjetas."
            ),
            "presentation_mode": "mixed" if has_items else "text",
            "response_title": "Calificación y Análisis de tu Perchero",
            "suggested_actions": suggested_actions[:5],
            "llm_max_tokens": 400,
        }

    def get_system_prompt(self) -> str:
        return (
            "Eres Altair, el Personal Stylist & Director Creativo de DrapeMind Atelier.\n"
            "MISION: Calificar, asesorar y elevar el guardarropa y la bolsa de compras del cliente con máxima autoridad de moda y criterio editorial.\n"
            "DIRECTRICES:\n"
            "1. CERO EMOJIS: Prohibido terminantemente cualquier emoji o emoticono.\n"
            "2. USA DATOS REALES: Basa tu análisis exclusivamente en las prendas, precios en Bolivianos (Bs) y stock verificado por FastAPI.\n"
            "3. INMERSIÓN Y PERSONALIZACIÓN: Saluda al cliente por su nombre de pila si está disponible, califica la armonía del conjunto del 1 al 10, analiza la textura y corte de cada prenda y propón mejoras y combinaciones concretas."
        )
