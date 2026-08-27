from typing import Any
from sqlalchemy.orm import Session
from app.models import User
from app.services.ai_skills.base_skill import BaseAiSkill
from app.services.ai_tools import ToolContext, execute_tool


class OrdersSkill(BaseAiSkill):
    """Maneja el seguimiento de pedidos, compras y reservas del usuario."""

    name: str = "orders_skill"
    description: str = "Seguimiento de compras realizadas, reservas y estado de entrega."

    def can_handle(self, message: str, context: dict[str, Any]) -> bool:
        clean = message.lower()
        if any(w in clean for w in ["carrito", "perchero", "bolsa", "camisa", "pantalon", "ropa", "buscame", "presupuesto"]):
            return False
        return any(w in clean for w in ["pedido", "pedidos", "mis compras", "mi compra", "reserva", "reservas", "mis ordenes", "mis órdenes", "cuando llega", "cuándo llega", "seguimiento"])

    def execute(self, db: Session, user: User, message: str, context: dict[str, Any]) -> dict[str, Any]:
        clean = message.lower()
        if "reserva" in clean or "apartado" in clean:
            tool_name = "get_my_reservations"
        else:
            tool_name = "get_my_orders"

        tool_res = execute_tool(tool_name, {}, ToolContext(db=db, user=user))
        action_items = []

        if isinstance(tool_res, list):
            if tool_name == "get_my_orders":
                for o in tool_res[:4]:
                    action_items.append({
                        "id": o.get("id"),
                        "variante_id": o.get("id"),
                        "nombre": f"Pedido #{o.get('id')}",
                        "precio": float(o.get("total_bob") or 0.0),
                        "color": f"Modalidad: {o.get('delivery') or 'Tienda'}",
                        "talla": f"Ref: {str(o.get('code', ''))[:8]}",
                        "sku": f"Fecha: {str(o.get('created_at', ''))[:10]}",
                        "imagen": None,
                        "accion": "VER_PEDIDO",
                        "motivo": f"Estado: {o.get('status') or 'REGISTRADO'}",
                    })
            else:
                for r in tool_res[:4]:
                    action_items.append({
                        "id": r.get("id"),
                        "variante_id": r.get("id"),
                        "nombre": f"Reserva #{r.get('id')}",
                        "precio": float(r.get("precio") or 0.0),
                        "color": f"Vence: {str(r.get('vence_at', ''))[:16]}",
                        "talla": f"Ref: {str(r.get('code', ''))[:8]}",
                        "sku": f"Estado: {r.get('status') or 'CONFIRMADA'}",
                        "imagen": None,
                        "accion": "VER_RESERVA",
                        "motivo": f"48h Showroom · {r.get('status') or 'CONFIRMADA'}",
                    })

        raw_name = getattr(user, "nombre", None)
        user_name = raw_name.split()[0] if raw_name else "estimado cliente"

        if tool_name == "get_my_orders":
            if action_items:
                direct = (
                    f"Estimado {user_name}, he consultado tus registros de compra. "
                    f"Tienes {len(action_items)} pedido(s) activos en el atelier. Puedes ver los detalles en las tarjetas adjuntas."
                )
            else:
                direct = f"Estimado {user_name}, no tienes pedidos registrados actualmente en tu cuenta."
        else:
            if action_items:
                direct = (
                    f"Estimado {user_name}, tienes {len(action_items)} reserva(s) activa(s) por 48 horas para pruebas en showroom. "
                    "Recuerda que puedes acercarte al atelier con tu código antes de su vencimiento."
                )
            else:
                direct = f"Estimado {user_name}, no tienes reservas de 48h vigentes en este momento."

        return {
            "tool_name": tool_name,
            "tool_args": {},
            "tool_result": tool_res,
            "action_items": action_items,
            "requires_llm": True,
            "direct_response": None,
            "fallback_response": direct,
            "focus_prompt": "Detalla el estado y referencia de los pedidos o reservas del cliente con suma cortesía.",
            "presentation_mode": "mixed" if action_items else "text",
            "response_title": "Tus Pedidos y Reservas en el Atelier",
            "suggested_actions": [
                {"label": "Armar outfit para cena", "prompt": "Arma un outfit elegante para una cena con presupuesto de Bs 700"},
                {"label": "Ver mi perchero actual", "prompt": "Revisa mi carrito de compras"},
            ],
            "llm_max_tokens": 200,
        }

    def get_system_prompt(self) -> str:
        return (
            "Eres Altair, el Asistente de Gestión y Atención de DrapeMind Atelier.\n"
            "MISION: Informar con precisión sobre el estado de compras y reservas 48h.\n"
            "DIRECTRICES: Cero emojis, datos exactos y tono formal distinguido."
        )
