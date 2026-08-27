from typing import Any
from sqlalchemy.orm import Session
from app.models import User
from app.services.ai_skills.base_skill import BaseAiSkill
from app.services.ai_tools import ToolContext, execute_tool
from app.services.store import get_product_detail


class OptimizeOutfitSkill(BaseAiSkill):
    """Habilidad experta en optimización de guardarropa, equilibrio entre calidad duradera vs costo accesible (Cost-Per-Wear e inversión textil)."""

    name: str = "optimize_outfit_skill"
    description: str = "Optimización de presupuesto, equilibrio entre piezas de alta durabilidad (Q4/Q5) y básicos accesibles (Q2/Q3)."

    OPTIMIZE_INTENTS = [
        "optimiza", "optimizar", "durabilidad", "que dure", "que me dure",
        "inversion", "inversión", "evitar comprar cosas baratas", "calidad vs",
        "vs calidad", "gastar bien", "costo por uso", "armario capsula", "armario cápsula",
        "equilibrar presupuesto", "equilibrar calidad", "mejor relacion calidad",
        "mejor relación calidad", "calidad duradera",
    ]

    def can_handle(self, message: str, context: dict[str, Any]) -> bool:
        clean = message.lower()
        return any(intent in clean for intent in self.OPTIMIZE_INTENTS)

    def execute(self, db: Session, user: User, message: str, context: dict[str, Any]) -> dict[str, Any]:
        tool_ctx = ToolContext(db=db, user=user)

        # 1. Obtener prendas de alta durabilidad (Q4 / Q5) y prendas accesibles optimizadas (Q2 / Q3)
        high_quality_prods = execute_tool("search_products_ai", {"calidad_min": 4, "limit": 10}, tool_ctx)
        value_prods = execute_tool("search_products_ai", {"calidad_max": 3, "limit": 10}, tool_ctx)

        # Fallback a trending si alguna lista está vacía
        if not isinstance(high_quality_prods, list) or not high_quality_prods:
            trending = execute_tool("get_trending_pieces", {"limit": 10}, tool_ctx)
            high_quality_prods = [p for p in (trending if isinstance(trending, list) else []) if (p.get("calidad_nivel") or 3) >= 4]
            value_prods = [p for p in (trending if isinstance(trending, list) else []) if (p.get("calidad_nivel") or 3) <= 3]

        selected_action_items = []
        outfit_pieces = []
        total_price = 0.0

        # Seleccionar 1 pieza de inversión clave (Pantalón, Chaqueta o Vestido Q4/Q5)
        investment_piece = None
        for p in (high_quality_prods if isinstance(high_quality_prods, list) else []):
            detail = get_product_detail(db, p["id"])
            variant = next(
                (v for v in detail.get("variantes", []) if v.get("activo") and (v.get("stock_disponible") or 0) > 0),
                None,
            )
            if variant:
                investment_piece = {
                    "id": p["id"],
                    "variante_id": variant["id"],
                    "nombre": p["nombre"],
                    "precio": float(p.get("precio") or 0),
                    "calidad": p.get("calidad_nivel") or 5,
                    "material": p.get("material") or "Tejido Sastrero Premium",
                    "color": variant.get("color"),
                    "talla": variant.get("talla"),
                    "imagen": variant.get("imagen") or ((p.get("imagenes") or [None])[0]),
                    "tipo": "INVERSIÓN_ALTA_DURABILIDAD",
                    "justificacion": f"Pieza estructural de Calidad Q{p.get('calidad_nivel') or 5} en {p.get('material') or 'fibra noble'}. Diseñada para resistir años de uso sin perder forma ni textura.",
                }
                break

        # Seleccionar 2 piezas de costo optimizado (Polera, Top, Accesorio Q2/Q3)
        value_pieces = []
        for p in (value_prods if isinstance(value_prods, list) else []):
            if investment_piece and p["id"] == investment_piece["id"]:
                continue
            detail = get_product_detail(db, p["id"])
            variant = next(
                (v for v in detail.get("variantes", []) if v.get("activo") and (v.get("stock_disponible") or 0) > 0),
                None,
            )
            if variant:
                value_pieces.append({
                    "id": p["id"],
                    "variante_id": variant["id"],
                    "nombre": p["nombre"],
                    "precio": float(p.get("precio") or 0),
                    "calidad": p.get("calidad_nivel") or 3,
                    "material": p.get("material") or "Algodón Confort",
                    "color": variant.get("color"),
                    "talla": variant.get("talla"),
                    "imagen": variant.get("imagen") or ((p.get("imagenes") or [None])[0]),
                    "tipo": "BASICO_OPTIMIZADO",
                    "justificacion": f"Básico inteligente Q{p.get('calidad_nivel') or 3} con alta rotación y excelente costo-beneficio.",
                })
                if len(value_pieces) >= 2:
                    break

        if investment_piece:
            outfit_pieces.append(investment_piece)
            total_price += investment_piece["precio"]
            selected_action_items.append({
                "id": investment_piece["id"],
                "variante_id": investment_piece["variante_id"],
                "nombre": investment_piece["nombre"],
                "color": investment_piece["color"],
                "talla": investment_piece["talla"],
                "precio": investment_piece["precio"],
                "imagen": investment_piece["imagen"],
                "accion": "AGREGAR",
                "motivo": f"Inversión de alta durabilidad (Calidad Q{investment_piece['calidad']})",
            })

        for vp in value_pieces:
            outfit_pieces.append(vp)
            total_price += vp["precio"]
            selected_action_items.append({
                "id": vp["id"],
                "variante_id": vp["variante_id"],
                "nombre": vp["nombre"],
                "color": vp["color"],
                "talla": vp["talla"],
                "precio": vp["precio"],
                "imagen": vp["imagen"],
                "accion": "AGREGAR",
                "motivo": f"Básico optimizado en precio (Calidad Q{vp['calidad']})",
            })

        avg_quality = (
            sum(p["calidad"] for p in outfit_pieces) / len(outfit_pieces)
            if outfit_pieces
            else 4.0
        )

        raw_name = getattr(user, "nombre", None)
        user_name = raw_name.split()[0] if raw_name else "estimado cliente"

        editorial_analysis = [
            "He diseñado una estrategia de optimización textil para maximizar el valor de tu presupuesto sin comprometer la longevidad de tu guardarropa.",
            f"El conjunto alcanza un índice de calidad promedio de Q{avg_quality:.1f} / 5.0.",
        ]

        if investment_piece:
            editorial_analysis.append(
                f"Pieza de inversión angular: {investment_piece['nombre']} (Bs {investment_piece['precio']:.2f}, {investment_piece['material']}). "
                f"Nivel Q{investment_piece['calidad']} de alta durabilidad, caída impecable y máxima resistencia al uso continuo."
            )

        if value_pieces:
            vp_desc = ", ".join(f"{vp['nombre']} (Bs {vp['precio']:.2f})" for vp in value_pieces)
            editorial_analysis.append(
                f"Básicos complementarios de alta rotación: {vp_desc}. Optimizan el presupuesto manteniendo una silueta refinada."
            )

        editorial_analysis.extend([
            f"Inversión total calculada: Bs {total_price:.2f} por las {len(outfit_pieces)} piezas verificadas.",
            "Gracias a la durabilidad de la pieza angular, el costo por postura estimado se reduce a menos de Bs 6.50 por uso.",
            "A continuación puedes explorar cada prenda, probarla en el espejo AR o añadir el conjunto a tu perchero."
        ])

        fallback_text = "\n\n".join(editorial_analysis)

        suggested_actions = [
            {"label": "Sugerir calzado de inversión", "prompt": "Qué calzado de alta calidad y durabilidad combina con este conjunto?"},
            {"label": "Calificar mi carrito actual", "prompt": "Piensa si mi lista en mi carrito está bien equilibrada del 1 al 10"},
            {"label": "Ver opciones para cena elegante", "prompt": "Arma un outfit elegante para una cena con presupuesto de Bs 700"},
            {"label": "Recomendar abrigo de lana", "prompt": "Muestra abrigos y chaquetas sastreras de máxima calidad Q5"},
        ]

        return {
            "tool_name": "optimize_outfit_skill",
            "tool_args": {"query": message},
            "tool_result": {
                "outfit_pieces": outfit_pieces,
                "total_price": total_price,
                "avg_quality": avg_quality,
            },
            "action_items": selected_action_items,
            "requires_llm": True,
            "direct_response": None,
            "fallback_response": fallback_text,
            "focus_prompt": (
                f"Asesora al cliente {user_name} sobre cómo equilibrar calidad de larga duración (Q4/Q5) vs piezas accesibles (Q2/Q3). "
                f"Explica por qué comprar prendas estructurales de alta calidad evita gastos repetidos en ropa barata que se deforma. "
                f"Presenta el total de Bs {total_price:.2f} y el índice de calidad Q{avg_quality:.1f}."
            ),
            "presentation_mode": "outfit",
            "response_title": "Estrategia de Optimización: Calidad vs Presupuesto",
            "response_meta": {
                "kind": "outfit",
                "occasion": "Estrategia de Inversión y Calidad",
                "total_bob": total_price,
                "budget_bob": None,
                "budget_remaining_bob": None,
            },
            "suggested_actions": suggested_actions,
            "llm_max_tokens": 400,
        }

    def get_system_prompt(self) -> str:
        return (
            "Eres Altair, el Asesor Senior de Imagen y Estrategia Textil de DrapeMind Atelier.\n"
            "MISION: Explicar con maestría editorial y técnica cómo equilibrar piezas de inversión duraderas (Q4/Q5) con básicos accesibles (Q2/Q3).\n"
            "REGLAS ESTRICTAS:\n"
            "1. CERO EMOJIS: Prohibido cualquier emoji o emoticono.\n"
            "2. DATOS REALES: Cita exclusivamente las prendas, precios en Bolivianos (Bs) y calidad devuelta por FastAPI.\n"
            "3. TONO EDITORIAL Y PRÁCTICO: Explica el costo por uso (Cost-Per-Wear), resistencia de telas nobles vs desventajas de comprar ropa de mala calidad que no dura."
        )
