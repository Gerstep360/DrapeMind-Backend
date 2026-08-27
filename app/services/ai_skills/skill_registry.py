from typing import Any
from app.services.ai_skills.base_skill import BaseAiSkill
from app.services.ai_skills.cart_skill import CartSkill
from app.services.ai_skills.optimize_outfit_skill import OptimizeOutfitSkill
from app.services.ai_skills.outfit_skill import OutfitSkill
from app.services.ai_skills.general_chat_skill import GeneralChatSkill
from app.services.ai_skills.orders_skill import OrdersSkill
from app.services.ai_skills.catalog_skill import CatalogSkill
from app.services.ai_skills.composite_skill import CompositeSkill


class SkillRegistry:
    """Registro y orquestador multi-habilidad adaptativo para DrapeMind AI."""

    def __init__(self) -> None:
        # Habilidades especializadas de dominio
        self.primary_skills: list[BaseAiSkill] = [
            CartSkill(),
            OptimizeOutfitSkill(),
            OutfitSkill(),
            OrdersSkill(),
            GeneralChatSkill(),
        ]
        self.catalog_skill = CatalogSkill()
        self.default_skill = self.catalog_skill

    def resolve(self, message: str, context: dict[str, Any] | None = None) -> BaseAiSkill:
        """Resuelve de forma adaptativa una o múltiples habilidades solapadas."""
        ctx = context or {}

        # 1. Evaluar coincidencias en habilidades primarias
        matched_primary = [s for s in self.primary_skills if s.can_handle(message, ctx)]

        if len(matched_primary) > 1:
            # Multi-skill solapado: coordinar ejecución compuesta
            return CompositeSkill(matched_primary)
        elif len(matched_primary) == 1:
            return matched_primary[0]

        # 2. Si no coincide ninguna primaria, consultar el catálogo general o fallback adaptativo
        if self.catalog_skill.can_handle(message, ctx):
            return self.catalog_skill

        return self.default_skill


skill_registry = SkillRegistry()
