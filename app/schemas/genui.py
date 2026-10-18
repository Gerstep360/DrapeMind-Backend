"""Allowlisted UI proposals. The model selects IDs; the server owns card data/actions."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class QuestionOption(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str = Field(min_length=1, max_length=80)
    prompt: str = Field(min_length=1, max_length=300)


class UIProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["product_grid", "question_options", "tool_result"]
    source_tool: (
        Literal[
            "get_my_shopping_context",
            "discover_for_me",
            "recommend_pickup_branches",
            "plan_more_for_less",
            "find_cart_savings",
            "compare_products",
            "get_stock",
            "get_branch_availability",
            "calculate_cart_totals",
            "calculate_selection_budget",
            "get_my_orders",
            "get_my_reservations",
            "get_my_payment_status",
            "get_store_policy",
        ]
        | None
    ) = None
    title: str = Field(default="", max_length=120)
    product_ids: list[int] = Field(default_factory=list, max_length=6)
    options: list[QuestionOption] = Field(default_factory=list, max_length=3)

    def resolve(self, known_cards: list[dict]) -> dict:
        if self.type == "tool_result":
            if not self.source_tool or self.product_ids or self.options:
                raise ValueError(
                    "El resultado requiere una fuente consultada, sin datos generados por el modelo."
                )
            return {"type": self.type, "source_tool": self.source_tool}
        if self.source_tool:
            raise ValueError("Esta presentación no admite una fuente de consulta.")
        if self.type == "question_options":
            if self.product_ids or not self.options:
                raise ValueError("Las preguntas requieren opciones, sin productos.")
            return {
                "type": self.type,
                "title": self.title,
                "options": [option.model_dump() for option in self.options],
            }
        known = {
            card["id"]: card for card in known_cards if card.get("accion") == "AGREGAR"
        }
        if (
            self.options
            or not self.product_ids
            or any(identity not in known for identity in self.product_ids)
        ):
            raise ValueError(
                "La UI solo puede mostrar productos verificados en esta conversación."
            )
        return {
            "type": self.type,
            "title": self.title,
            "product_ids": list(dict.fromkeys(self.product_ids)),
            "actions": ["view_product", "add_to_cart"],
        }
