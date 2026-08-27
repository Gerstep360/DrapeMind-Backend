from typing import Any
from sqlalchemy.orm import Session
from app.models import User
from app.services.ai_skills.base_skill import BaseAiSkill
from app.services.ai_tools import ToolContext, execute_tool
from app.services.store import get_product_detail


class CatalogSkill(BaseAiSkill):
    """Maneja la búsqueda de prendas por palabra clave, calidad, tipo o presupuesto."""

    name: str = "catalog_skill"
    description: str = "Búsqueda ágil de prendas específicas en el catálogo y verificación de stock real."

    KNOWN_SIZES = {"XXL", "XL", "XS", "S", "M", "L", "36", "38", "39", "40", "41", "42", "43", "44", "45", "46", "28", "30", "32", "34"}

    def can_handle(self, message: str, context: dict[str, Any]) -> bool:
        return True

    def execute(self, db: Session, user: User, message: str, context: dict[str, Any]) -> dict[str, Any]:
        clean = message.lower()

        # Extraer vocabulario de prendas, telas o colores reales
        GARMENT_VOCABULARY = [
            "polera", "poleras", "camisa", "camisas", "blusa", "blusas", "polo", "polos",
            "pantalon", "pantalón", "pantalones", "jean", "jeans", "falda", "faldas",
            "vestido", "vestidos", "chaqueta", "chaquetas", "abrigo", "abrigos", "blazer", "blazers",
            "zapato", "zapatos", "zapatilla", "zapatillas", "bota", "botas", "mocasines",
            "bufanda", "cinturon", "cinturón", "lino", "seda", "algodon", "algodón", "cuero", "lana", "denim",
            "negro", "blanco", "azul", "beige", "verde", "gris", "rojo", "marfil", "dorado", "plata"
        ]
        query_words = [w for w in GARMENT_VOCABULARY if w in clean]
        query = " ".join(query_words) if query_words else ""

        tokens = [w for w in clean.replace(",", " ").replace(".", " ").replace("?", " ").split() if len(w) > 2]
        max_price = None
        requested_size = None
        for i, w in enumerate(tokens):
            if w in ("talla", "size") and i + 1 < len(tokens):
                candidate = tokens[i + 1].upper()
                if candidate in self.KNOWN_SIZES:
                    requested_size = candidate
            elif w in ("bs", "bob", "presupuesto", "tope", "menos", "maximo", "máximo") and i + 1 < len(tokens):
                num_str = "".join(c for c in tokens[i + 1] if c.isdigit())
                if num_str:
                    max_price = float(num_str)

        # Si el usuario pide exclusivas / calidad / tendencia
        min_quality = None
        if any(k in clean for k in ["exclusiv", "lujo", "alta calidad", "q5", "q4", "tendencia", "top"]):
            min_quality = 4

        tool_args: dict[str, Any] = {"limit": 4}
        if query:
            tool_args["query"] = query
        if max_price:
            tool_args["max_price"] = max_price
        if requested_size:
            tool_args["size"] = requested_size
        if min_quality:
            tool_args["calidad_min"] = min_quality

        # Decidir qué herramienta invocar
        if any(k in clean for k in ["tendencia", "exclusiv", "destacad", "mas vendid", "más vendid"]):
            tool_res = execute_tool("get_trending_pieces", {"limit": 4}, ToolContext(db=db, user=user))
            tool_name = "get_trending_pieces"
        elif any(k in clean for k in ["novedad", "nuevo", "nueva", "recien", "llegad"]):
            tool_res = execute_tool("get_new_arrivals", {"limit": 4}, ToolContext(db=db, user=user))
            tool_name = "get_new_arrivals"
        else:
            tool_res = execute_tool("search_products", tool_args, ToolContext(db=db, user=user))
            tool_name = "search_products"

        action_items = []
        if isinstance(tool_res, list):
            for p in tool_res[:4]:
                detail = get_product_detail(db, p["id"])
                variant = None
                if detail.get("variantes"):
                    if requested_size:
                        variant = next(
                            (v for v in detail["variantes"] if v.get("talla", "").upper() == requested_size and v.get("activo") and (v.get("stock_disponible") or 0) > 0),
                            None,
                        )
                    if not variant:
                        variant = next(
                            (v for v in detail["variantes"] if v.get("activo") and (v.get("stock_disponible") or 0) > 0),
                            detail["variantes"][0],
                        )

                color = variant.get("color") if variant else "Tono único"
                talla = variant.get("talla") if variant else (requested_size or "Única")
                vid = variant.get("id") if variant else None
                img = (variant.get("imagen") if variant else None) or ((p.get("imagenes") or [None])[0])

                motivo = f"Calidad Q{p.get('calidad_nivel') or 3}"
                if requested_size and variant and variant.get("talla", "").upper() == requested_size:
                    motivo += f" · Talla {requested_size} disponible"

                action_items.append({
                    "id": p.get("id"),
                    "variante_id": vid,
                    "nombre": p.get("nombre"),
                    "color": color,
                    "talla": talla,
                    "sku": variant.get("sku") if variant else None,
                    "precio": float(p.get("precio") or 0),
                    "imagen": img,
                    "accion": "AGREGAR",
                    "motivo": motivo,
                })

        raw_name = getattr(user, "nombre", None)
        user_name = raw_name.split()[0] if raw_name else "estimado cliente"

        if action_items:
            fallback = (
                f"Estimado {user_name}, he seleccionado {len(action_items)} pieza(s) con stock verificado en showroom "
                + (f"para tu búsqueda '{query}'." if query else "de las piezas más destacadas del atelier.")
            )
        else:
            fallback = (
                f"Estimado {user_name}, no encontré prendas disponibles con esos filtros exactos. "
                "¿Deseas que busquemos en otra talla o te presente las novedades generales del showroom?"
            )

        suggested_actions = [
            {"label": "Armar outfit para cena", "prompt": "Arma un outfit elegante para una cena con presupuesto de Bs 700"},
            {"label": "Optimizar calidad vs precio", "prompt": "Optimiza mi outfit equilibrando prendas de calidad y durabilidad vs precio"},
            {"label": "Ver mi perchero actual", "prompt": "Revisa mi carrito de compras"},
        ]

        return {
            "tool_name": tool_name,
            "tool_args": tool_args,
            "tool_result": tool_res,
            "action_items": action_items,
            "requires_llm": True,
            "direct_response": None,
            "fallback_response": fallback,
            "focus_prompt": f"Presenta las {len(action_items)} prendas encontradas para {user_name} destacando materiales y calidad Q1-Q5.",
            "presentation_mode": "mixed" if action_items else "text",
            "response_title": f"Selección Showroom: {query.capitalize() if query else 'Piezas Destacadas'}",
            "suggested_actions": suggested_actions[:4],
            "llm_max_tokens": 260,
        }

    def get_system_prompt(self) -> str:
        return (
            "Eres Altair, el Asesor de Moda y Curador de DrapeMind Atelier.\n"
            "MISION: Presentar prendas de alta gama, describir cortes y composiciones textiles con suma elocuencia.\n"
            "DIRECTRICES: Cero emojis, cita precios en Bolivianos (Bs) y responde con concisión y elegancia."
        )
