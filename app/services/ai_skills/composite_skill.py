from typing import Any
from sqlalchemy.orm import Session
from app.models import User
from app.services.ai_skills.base_skill import BaseAiSkill


class CompositeSkill(BaseAiSkill):
    """Habilidad compuesta (Multi-Skill Pipeline) que coordina y fusiona la ejecución de múltiples habilidades cuando el usuario formula solicitudes combinadas o solapadas en un solo mensaje."""

    name: str = "composite_skill"
    description: str = "Coordinador multi-habilidad que ejecuta y fusiona herramientas, tarjetas y razonamiento de varias skills en una sola respuesta."

    def __init__(self, skills: list[BaseAiSkill]) -> None:
        self.active_skills = skills

    def can_handle(self, message: str, context: dict[str, Any]) -> bool:
        return len(self.active_skills) > 1

    def execute(self, db: Session, user: User, message: str, context: dict[str, Any]) -> dict[str, Any]:
        combined_action_items = []
        combined_notices = []
        combined_tools_results = []
        combined_tools_names = []
        combined_suggested_actions = []
        narrative_sections = []
        response_titles = []
        raw_name = getattr(user, "nombre", None)
        user_name = raw_name.split()[0] if raw_name else "estimado cliente"

        # Ejecutar cada skill detectada en la baraja de habilidades
        for skill in self.active_skills:
            res = skill.execute(db, user, message, context)
            if res.get("tool_name"):
                combined_tools_names.append(res["tool_name"])
                combined_tools_results.append({
                    "name": res["tool_name"],
                    "args": res.get("tool_args") or {},
                    "result": res.get("tool_result"),
                })
            if res.get("action_items"):
                combined_action_items.extend(res["action_items"])
            if res.get("notices"):
                combined_notices.extend(res["notices"])
            if res.get("suggested_actions"):
                combined_suggested_actions.extend(res["suggested_actions"])
            if res.get("response_title"):
                response_titles.append(res["response_title"])
            if res.get("fallback_response"):
                narrative_sections.append(res["fallback_response"])

        # Deduplicar action items por ID o variante_id
        seen_ids = set()
        unique_action_items = []
        for item in combined_action_items:
            key = (item.get("id"), item.get("variante_id"), item.get("accion"))
            if key not in seen_ids:
                seen_ids.add(key)
                unique_action_items.append(item)

        # Deduplicar suggested action chips
        seen_prompts = set()
        unique_suggested_actions = []
        for chip in combined_suggested_actions:
            p = chip.get("prompt")
            if p and p not in seen_prompts:
                seen_prompts.add(p)
                unique_suggested_actions.append(chip)

        composite_title = " · ".join(response_titles) if response_titles else "Asesoría Integral DrapeMind"

        # Ensamblar narrativa compuesta fluida y natural sin saludos repetidos
        clean_sections = []
        for sec in narrative_sections:
            text = sec.strip()
            # Remover saludos redundantes de cada sub-habilidad
            for prefix in [f"Saludos, {user_name}.", "Saludos,", f"Hola, {user_name}.", "Hola,"]:
                if text.startswith(prefix):
                    text = text[len(prefix):].strip()
            if text:
                clean_sections.append(text)

        composite_narrative = (
            f"Saludos, {user_name}.\n\n"
            + "\n\n".join(clean_sections)
            if clean_sections
            else f"Saludos, {user_name}. He analizado tu consulta para brindarte una asesoría estilística completa."
        )

        focus_prompt = (
            f"El cliente {user_name} formuló una consulta compuesta que involucra múltiples aspectos: {', '.join(s.name for s in self.active_skills)}. "
            "Sintetiza una respuesta fluida, elegante y cohesionada en tono de estilista de alta costura, integrando todas las piezas analizadas de forma armónica."
        )

        return {
            "tool_name": "multi_skill_pipeline" if combined_tools_names else None,
            "tool_args": {"sub_tools": combined_tools_names},
            "tool_result": combined_tools_results,
            "composite_sub_tools": combined_tools_results,
            "action_items": unique_action_items[:8],
            "requires_llm": True,
            "direct_response": None,
            "fallback_response": composite_narrative,
            "focus_prompt": focus_prompt,
            "presentation_mode": "mixed" if unique_action_items else "text",
            "response_title": composite_title,
            "notices": combined_notices,
            "suggested_actions": unique_suggested_actions[:6],
            "llm_max_tokens": 500,
        }

    def get_system_prompt(self) -> str:
        sub_prompts = "\n".join(s.get_system_prompt() for s in self.active_skills)
        return (
            "Eres el Personal Stylist & Director Integral de DrapeMind Atelier.\n"
            "MISION: Integrar múltiples áreas (carrito, compras, outfits, optimización de presupuesto y catálogo) en una sola respuesta experta.\n"
            "REGLAS:\n"
            "1. CERO EMOJIS: Prohibido cualquier emoji.\n"
            "2. DATOS REALES: Cita exclusivamente precios en Bs, prendas y stock verificado por FastAPI.\n"
            "3. RESPUESTA FLUIDA Y COHERENTE: Responde todas las partes de la solicitud del cliente de manera armónica.\n\n"
            f"Directrices específicas combinadas:\n{sub_prompts}"
        )
