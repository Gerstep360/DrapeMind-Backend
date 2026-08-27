from typing import Any
from sqlalchemy.orm import Session
from app.models import User
from app.services.ai_skills.base_skill import BaseAiSkill
from app.services.ai_tools import ToolContext, execute_tool


class OutfitSkill(BaseAiSkill):
    """Maneja el armado de looks y outfits completos coordinados por ocasión y presupuesto."""

    name: str = "outfit_skill"
    description: str = "Recomendación de outfits completos según ocasión (cena, fiesta, casual, trabajo) y presupuesto."

    KNOWN_SIZES = {"XXL", "XL", "XS", "S", "M", "L", "36", "38", "39", "40", "41", "42", "43", "44", "45", "46", "28", "30", "32", "34"}

    @classmethod
    def _extract_sizes(cls, clean: str, garment_keywords: list[str]) -> list[str]:
        """Extrae de forma semántica y limpia las tallas cercanas a prendas especificadas."""
        words = clean.replace(",", " ").replace(".", " ").replace(":", " ").replace(";", " ").split()
        found = []
        for i, w in enumerate(words):
            upper_w = w.upper()
            if upper_w in cls.KNOWN_SIZES:
                window = words[max(0, i - 4):min(len(words), i + 5)]
                window_str = " ".join(window)
                if any(gk in window_str for gk in garment_keywords):
                    found.append(upper_w)
        return list(dict.fromkeys(found))

    def can_handle(self, message: str, context: dict[str, Any]) -> bool:
        clean = message.lower()
        if "carrito" in clean or "perchero" in clean or "bolsa" in clean:
            if not any(k in clean for k in ["arma", "crea", "nuevo", "outfit", "outift", "look", "para cena", "para fiesta"]):
                return False
        return any(k in clean for k in ["outfit", "outift", "look", "conjunto", "combin", "vestir", "asesor", "recomiend", "gala", "fiesta", "boda", "cena", "trabajo", "sueldo", "cara", "caro", "lujo", "exclusiv"])

    def execute(self, db: Session, user: User, message: str, context: dict[str, Any]) -> dict[str, Any]:
        clean = message.lower()
        is_luxury = any(k in clean for k in ["mas cara", "más cara", "mas caras", "más caras", "lo más caro", "lo mas caro", "mas caro", "más caro", "lujo", "exclusiv", "sueldo", "alta gama", "q5"])

        occasion = "casual"
        if is_luxury:
            occasion = "gala y exclusividad"
        elif "cena" in clean:
            occasion = "cena"
        elif "fiesta" in clean or "boda" in clean or "gala" in clean:
            occasion = "fiesta"
        elif "trabajo" in clean or "oficina" in clean:
            occasion = "trabajo"

        # Extraer max_price si fue especificado
        max_price = None
        words = clean.replace(":", " ").replace("=", " ").replace("$", " ").split()
        for i, w in enumerate(words):
            if w in ("bs", "bob", "presupuesto", "tope", "maximo", "máximo", "hasta", "menos"):
                for offset in (1, 2, -1):
                    target_idx = i + offset
                    if 0 <= target_idx < len(words):
                        cleaned_val = words[target_idx].replace("bs", "").replace("bob", "")
                        if cleaned_val.isdigit():
                            max_price = float(cleaned_val)
                            break
                if max_price:
                    break

        top_sizes = self._extract_sizes(clean, ["polera", "camisa", "blusa", "polo", "top", "superior"])
        bottom_sizes = self._extract_sizes(clean, ["pantalon", "pantalón", "jean", "falda", "inferior", "palazzo"])
        shoe_sizes = self._extract_sizes(clean, ["zapato", "zapatos", "calzado", "zapatilla", "botas", "mocasines"])

        memory = context.get("memory") or {}
        top_size = top_sizes[0] if top_sizes else None
        bottom_size = bottom_sizes[0] if bottom_sizes else None
        shoe_size = shoe_sizes[0] if shoe_sizes else None
        top_type = next(
            (item for item in ["polera", "camisa", "blusa", "polo"] if item in clean),
            None,
        )
        bottom_type = next(
            (item for item in ["pantalon", "jean", "falda"] if item in clean),
            None,
        )
        bottom_fit = None
        if any(item in clean for item in ["ancho", "holgado", "wide", "oversize"]):
            bottom_fit = "ancho"
        elif any(item in clean for item in ["ajustado", "skinny", "slim"]):
            bottom_fit = "ajustado"
        elif "recto" in clean:
            bottom_fit = "recto"

        # Medidas simples
        measurements = {}
        for part in ["pecho", "cintura", "cadera", "largo", "pie"]:
            if part in clean:
                p_idx = clean.find(part)
                substr = clean[p_idx:p_idx + 25]
                num_part = "".join(c for c in substr if c.isdigit() or c in ",.")
                if num_part:
                    try:
                        measurements[part] = float(num_part.replace(",", "."))
                    except ValueError:
                        pass

        tool_args = {"occasion": occasion}
        if max_price:
            tool_args["max_budget"] = max_price
        for key, value in {
            "top_size": top_size,
            "bottom_size": bottom_size,
            "shoe_size": shoe_size,
            "top_type": top_type,
            "bottom_type": bottom_type,
            "bottom_fit": bottom_fit,
        }.items():
            if value:
                tool_args[key] = value
        for key, value in {
            "top_sizes": top_sizes,
            "bottom_sizes": bottom_sizes,
            "shoe_sizes": shoe_sizes,
        }.items():
            if value:
                tool_args[key] = value

        recent_product_ids = [
            int(value)
            for value in memory.get("recommended_product_ids", [])
            if str(value).isdigit()
        ]
        if recent_product_ids:
            tool_args["exclude_product_ids"] = recent_product_ids[-24:]
        if measurements:
            tool_args["measurements"] = measurements

        tool_res = execute_tool("recommend_outfit", tool_args, ToolContext(db=db, user=user))
        action_items = []
        selected_products = []
        notices = []
        selected_total = 0.0

        if isinstance(tool_res, dict):
            groups = [
                tool_res.get("tops_sugeridos") or [],
                tool_res.get("inferiores_sugeridos") or [],
                tool_res.get("calzado_sugerido") or [],
                tool_res.get("complementos_abrigos") or [],
            ]
            for options in groups:
                if not options:
                    continue
                if is_luxury:
                    ordered = sorted(
                        options,
                        key=lambda item: (float(item.get("calidad_nivel") or 3), float(item.get("precio") or 0)),
                        reverse=True,
                    )
                    item = ordered[0]
                elif max_price:
                    ordered = sorted(options, key=lambda item: float(item.get("precio") or 0))
                    item = ordered[0]
                else:
                    ordered = sorted(
                        options,
                        key=lambda item: float(item.get("calidad_nivel") or 3),
                        reverse=True,
                    )
                    item = ordered[0]

                price = float(item.get("precio") or 0)
                if max_price is not None and selected_total + price > max_price:
                    continue
                selected_total += price
                selected_products.append(item)
                action_items.append({
                    "id": item.get("producto_id") or item.get("id"),
                    "variante_id": item.get("variante_id"),
                    "nombre": item.get("nombre"),
                    "color": item.get("color"),
                    "talla": item.get("talla"),
                    "precio": price,
                    "imagen": item.get("imagen"),
                    "accion": "AGREGAR",
                    "motivo": (
                        f"Talla {item.get('talla')} verificada · "
                        f"Calidad Q{item.get('calidad_nivel') or 3}"
                    ),
                })
            tool_res["seleccion_total"] = round(selected_total, 2)
            tool_res["seleccion"] = selected_products
            tool_res["presupuesto_cumplido"] = (
                max_price is None or selected_total <= max_price
            )
            for restriction in tool_res.get("restricciones_sin_stock") or []:
                notices.append(
                    {
                        "type": "warning",
                        "title": "Prenda no encontrada",
                        "message": restriction,
                    }
                )
            if measurements:
                formatted = ", ".join(
                    f"{name} {value:g} cm" for name, value in measurements.items()
                )
                notices.append(
                    {
                        "type": "info",
                        "title": "Medidas conservadas",
                        "message": (
                            f"Registré {formatted}. El catálogo actual no guarda medidas "
                            "exactas por variante, así que requieren validación antes de comprar."
                        ),
                    }
                )

        constraint_parts = [
            value
            for value in [
                f"parte superior talla {' o '.join(top_sizes)}" if top_sizes else None,
                f"parte inferior talla {' o '.join(bottom_sizes)}" if bottom_sizes else None,
                f"calzado talla {' o '.join(shoe_sizes)}" if shoe_sizes else None,
                f"pantalón {bottom_fit}" if bottom_fit else None,
            ]
            if value
        ]

        raw_name = getattr(user, "nombre", None)
        user_name = raw_name.split()[0] if raw_name else "estimado cliente"

        narrative = [
            f"Saludos, {user_name}. Para una ocasión {occasion}, he diseñado una composición exclusiva de {len(action_items)} piezas seleccionadas con stock y tallas verificadas.",
        ]

        if max_price:
            remaining = max_price - selected_total
            narrative.append(f"La propuesta totaliza una inversión de Bs {selected_total:.2f} (margen disponible de Bs {remaining:.2f} sobre tu presupuesto de Bs {max_price:.2f}).")
        else:
            narrative.append(f"La propuesta requiere una inversión total de Bs {selected_total:.2f} por el conjunto completo.")

        if constraint_parts:
            narrative.append(f"Criterios de silueta y talla aplicados: {', '.join(constraint_parts)}.")

        missing_text = " ".join(notice["message"] + "." for notice in notices)
        if notices:
            narrative.append(f"Observación de disponibilidad: {missing_text}")

        narrative.append("A continuación puedes explorar cada prenda en detalle, probarla en el probador virtual AR o cargar la selección completa a tu perchero.")
        fallback_response = "\n\n".join(narrative)
        response_meta = {
            "kind": "outfit",
            "total_bob": round(selected_total, 2),
            "budget_bob": max_price,
            "budget_remaining_bob": (
                round(max_price - selected_total, 2) if max_price is not None else None
            ),
            "item_count": len(action_items),
            "occasion": occasion,
            "can_add_all": bool(action_items),
            "replaces_cart": True,
        }

        suggested_actions = []
        if action_items:
            first_item = action_items[0]["nombre"]
            first_color = action_items[0]["color"]
            suggested_actions.append({
                "label": "Combinar con abrigo o blazer",
                "prompt": f"Qué chaqueta o abrigo combina mejor con {first_item} en tono {first_color}?",
            })
            if max_price and max_price > selected_total:
                diff = max_price - selected_total
                if diff >= 25:
                    suggested_actions.append({
                        "label": f"Añadir accesorio (Bs {diff:.0f} disp.)",
                        "prompt": f"Recomiéndame un accesorio o complemento utilizando los Bs {diff:.0f} restantes del presupuesto",
                    })

        if not shoe_sizes:
            suggested_actions.append({
                "label": "Ver calzado a juego",
                "prompt": f"Recomiéndame calzado formal o de atelier para completar este conjunto para ocasión {occasion}",
            })

        if occasion == "cena":
            suggested_actions.append({
                "label": "Adaptar para el día",
                "prompt": "Cómo puedo adaptar las prendas de este outfit para un evento diurno o casual?",
            })
        else:
            suggested_actions.append({
                "label": "Elevar a gala o noche",
                "prompt": "Cómo puedo transformar este look en una propuesta de gala nocturna?",
            })

        suggested_actions.append({
            "label": "Optimizar calidad vs precio",
            "prompt": "Optimiza este outfit equilibrando prendas de alta durabilidad y piezas accesibles",
        })

        return {
            "tool_name": "recommend_outfit",
            "tool_args": tool_args,
            "tool_result": tool_res,
            "action_items": action_items[:4],
            "requires_llm": True,
            "direct_response": None,
            "fallback_response": fallback_response,
            "focus_prompt": (
                f"Presenta y argumenta la propuesta de outfit de alta costura para {user_name} en ocasión {occasion}. "
                f"Total Bs {selected_total:.2f}. Explica la coherencia de telas y siluetas."
            ),
            "presentation_mode": "outfit",
            "response_title": f"Propuesta de Estilo · Ocasión {occasion.capitalize()}",
            "response_meta": response_meta,
            "notices": notices,
            "suggested_actions": suggested_actions[:5],
            "llm_max_tokens": 400,
        }

    def get_system_prompt(self) -> str:
        return (
            "Eres Altair, el Personal Stylist & Asesor de Imagen de DrapeMind Atelier.\n"
            "MISION: Armar looks y outfits de alta costura equilibrados y distinguidos.\n"
            "REGLAS:\n"
            "1. CERO EMOJIS: Prohibido terminantemente cualquier emoji o emoticono.\n"
            "2. USA DATOS REALES: Cita exclusivamente las prendas, precios en Bolivianos (Bs) y tallas de FastAPI.\n"
            "3. CRITERIO EDITORIAL: Explica cómo combinan las texturas, siluetas y colores."
        )
