from typing import Any
from sqlalchemy.orm import Session
from app.models import User
from app.services.ai_skills.base_skill import BaseAiSkill


class GeneralChatSkill(BaseAiSkill):
    """Maneja saludos, preguntas generales sobre DrapeMind, agradecimientos y consultas de estilismo generales sin requerir consultas pesadas de BD."""

    name: str = "general_chat_skill"
    description: str = "Atención conversacional inmediata, saludos, guía de servicios y preguntas frecuentes."

    def can_handle(self, message: str, context: dict[str, Any]) -> bool:
        clean = message.lower().strip()
        if any(term in clean for term in ["polera", "camisa", "pantalon", "jean", "vestido", "chaqueta", "abrigo", "falda", "outfit", "look", "carrito", "perchero", "pedido", "comprar"]):
            return False
        return any(w in clean for w in ["hola", "buen", "salud", "hey", "gracias", "ok", "vale", "quien eres", "que haces", "ayuda", "horario", "ubicacion", "tienda"])

    def execute(self, db: Session, user: User, message: str, context: dict[str, Any]) -> dict[str, Any]:
        clean = message.strip().lower()
        raw_name = getattr(user, "nombre", None)
        user_name = raw_name.split()[0] if raw_name else "estimado cliente"

        if any(w in clean for w in ["hola", "buen", "saludos", "hey", "que tal", "qué tal", "como estas", "cómo estás", "hello", "hi"]):
            direct = (
                f"Saludos, {user_name}. Soy Altair, tu Personal Stylist de DrapeMind. "
                "Puedo buscar prendas, equilibrar tu guardarropa o calificar tu perchero. ¿Qué look deseas diseñar?"
            )
            return {
                "tool_name": None,
                "tool_args": {},
                "tool_result": None,
                "action_items": [],
                "requires_llm": False,
                "direct_response": direct,
                "focus_prompt": "Saluda calidamente sin ejecutar herramientas.",
                "presentation_mode": "text",
                "response_title": "Bienvenido a DrapeMind Atelier",
                "suggested_actions": [
                    {"label": "Armar outfit para cena", "prompt": "Arma un outfit elegante para una cena con presupuesto de Bs 700"},
                    {"label": "Optimizar calidad vs precio", "prompt": "Optimiza mi outfit equilibrando prendas de calidad y durabilidad vs precio"},
                    {"label": "Calificar mi carrito del 1 al 10", "prompt": "Piensa si mi lista en mi carrito está bien equilibrada del 1 al 10"},
                    {"label": "Ver piezas exclusivas Q5", "prompt": "Muéstrame las piezas más exclusivas y de tendencia del atelier"},
                ],
                "llm_max_tokens": 160,
            }

        if any(w in clean for w in ["gracias", "muchas gracias", "genial", "perfecto", "entendido", "excelente", "ok", "vale"]):
            direct = (
                f"Con el mayor de los gustos, {user_name}. Si deseas agregar o cambiar alguna prenda de tu perchero, o requieres una recomendación adicional, aquí estaré a tu entera disposición."
            )
            return {
                "tool_name": None,
                "tool_args": {},
                "tool_result": None,
                "action_items": [],
                "requires_llm": False,
                "direct_response": direct,
                "focus_prompt": "Despedida o confirmacion amable.",
                "presentation_mode": "text",
                "response_title": None,
                "llm_max_tokens": 120,
            }

        if any(w in clean for w in ["horario", "donde", "dónde", "ubicacion", "ubicación", "tienda", "devolucion", "devolución", "guia de tallas", "guía de tallas"]):
            direct = (
                "Información de Servicio DrapeMind:\n\n"
                "- **Atelier Principal**: Atendemos de Lunes a Sábado de 09:00 a 20:00.\n"
                "- **Recojo y Pruebas**: Puedes reservar cualquier prenda en línea y probártela sin compromiso en tienda durante 30 minutos.\n"
                "- **Guías de Talla**: Disponemos de confección exacta en tallas S, M, L y XL con materiales certificados de calidad Q1 a Q5.\n"
                "- **Formas de Pago**: Aceptamos pagos en efectivo directo en caja y transferencias QR instantáneas."
            )
            return {
                "tool_name": None,
                "tool_args": {},
                "tool_result": None,
                "action_items": [],
                "requires_llm": False,
                "direct_response": direct,
                "focus_prompt": "Informacion corporativa.",
                "presentation_mode": "text",
                "response_title": None,
                "llm_max_tokens": 140,
            }

        return {
            "tool_name": None,
            "tool_args": {},
            "tool_result": None,
            "action_items": [],
            "requires_llm": True,
            "direct_response": None,
            "fallback_response": (
                f"Saludos, {user_name}. Como asesor de moda y curador de DrapeMind, "
                "puedo asistirte en la búsqueda de piezas exclusivas, armado de outfits y optimización de tu guardarropa."
            ),
            "focus_prompt": "Atiende cordialmente al cliente como Altair, consultor de moda de alta costura.",
            "presentation_mode": "text",
            "response_title": "Asesoría Altair",
            "suggested_actions": [
                {"label": "Armar outfit para cena", "prompt": "Arma un outfit elegante para una cena con presupuesto de Bs 700"},
                {"label": "Novedades del atelier", "prompt": "Muéstrame las piezas más exclusivas y de tendencia del showroom"},
            ],
            "llm_max_tokens": 200,
        }

    def get_system_prompt(self) -> str:
        return (
            "Eres Altair, el Personal Stylist & Asesor de Imagen de DrapeMind Atelier.\n"
            "MISION: Atender con distinción, amabilidad y máxima autoridad en diseño de moda."
        )
