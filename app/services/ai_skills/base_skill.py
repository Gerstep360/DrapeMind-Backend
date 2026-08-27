from abc import ABC, abstractmethod
from typing import Any
from sqlalchemy.orm import Session
from app.models import User


class BaseAiSkill(ABC):
    """Clase base para módulos de habilidades del Asistente DrapeMind."""

    name: str = "base_skill"
    description: str = "Habilidad base"

    @abstractmethod
    def can_handle(self, message: str, context: dict[str, Any]) -> bool:
        """Determina rápidamente si esta habilidad debe activarse para el mensaje."""
        pass

    @abstractmethod
    def execute(self, db: Session, user: User, message: str, context: dict[str, Any]) -> dict[str, Any]:
        """
        Ejecuta la lógica de la habilidad.
        Retorna un diccionario con:
          - "tool_name": nombre de la herramienta ejecutada (o None si es respuesta directa)
          - "tool_args": argumentos utilizados
          - "tool_result": resultado de la consulta
          - "action_items": prendas interactivas para agregar/quitar
          - "requires_llm": booleano indicando si requiere generación de texto con Gemma
          - "direct_response": texto directo si no requiere LLM
          - "focus_prompt": instrucción específica para orientar la respuesta de Gemma
          - "presentation_mode": "text", "cards" o "mixed"
          - "response_title": título corto para el bloque de tarjetas
          - "llm_max_tokens": límite pequeño para una respuesta rápida
        """
        pass

    def get_system_prompt(self) -> str:
        """Retorna el prompt de sistema especializado y compacto para esta habilidad."""
        return (
            "Eres el Personal Stylist de Alta Costura de DrapeMind.\n"
            "REGLAS:\n"
            "1. CERO EMOJIS: Prohibido cualquier emoji.\n"
            "2. Usa exclusivamente los datos devueltos por FastAPI.\n"
            "3. Sé conciso: entrega primero la decisión y evita repetir los datos de las tarjetas."
        )
