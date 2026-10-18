"""Server-owned clarification forms. Opening/completing a form never calls NVIDIA."""

from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

Goal = Literal["discover", "new_arrivals", "outfit", "branches", "budget", "savings"]
FieldName = Literal[
    "query",
    "category_id",
    "budget",
    "city",
    "occasion",
    "top_size",
    "bottom_size",
    "shoe_size",
    "color",
    "max_items",
    "keep_color",
]


class ShoppingQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    goal: Goal
    fields: list[FieldName] = Field(min_length=1, max_length=6)


GOALS = {
    "discover": (
        "Buscar prendas para mí",
        "Busca prendas para mí con estos criterios y mis preferencias guardadas.",
    ),
    "new_arrivals": (
        "Novedades para mí",
        "Consulta novedades reales de los últimos 30 días que encajen con mis preferencias.",
    ),
    "outfit": (
        "Crear mi look",
        "Crea un look con mis preferencias y los datos confirmados.",
    ),
    "branches": (
        "Elegir sucursal",
        "Compara sucursales para las cantidades de mi carrito según stock y ciudad.",
    ),
    "budget": (
        "Llevar más con mi presupuesto",
        "Calcula más prendas distintas dentro de mi presupuesto con mis tallas y gustos.",
    ),
    "savings": (
        "Ahorrar en mi carrito",
        "Busca sustituciones de menor precio para mi carrito, conservando cantidades y tallas. Calcula si caben prendas extra con el ahorro. Solo presenta la propuesta.",
    ),
}


def question_form(
    goal: Goal,
    context: dict,
    *,
    fields=None,
    request="",
    constraints=None,
    show_known=False,
):
    profile, constraints = context["profile"], constraints or {}

    def known(key, saved=None):
        return constraints.get(key, profile.get(saved or key))

    configs = {
        "query": ("¿Qué prenda buscas?", "text", "", []),
        "category_id": (
            "Tipo de prenda",
            "select",
            "",
            [
                {"value": str(c["id"]), "label": c["name"]}
                for c in context["categories"]
            ],
        ),
        "budget": (
            "Presupuesto total (Bs)",
            "number",
            known("budget", "presupuesto_habitual"),
            [],
        ),
        "city": (
            "Ciudad para recoger",
            "text",
            constraints.get("city") or context["city"],
            [],
        ),
        "occasion": (
            "Ocasión",
            "text",
            (profile.get("ocasiones_frecuentes") or [""])[0],
            [],
        ),
        "top_size": ("Talla superior", "text", known("top_size", "talla_superior"), []),
        "bottom_size": (
            "Talla inferior",
            "text",
            known("bottom_size", "talla_inferior"),
            [],
        ),
        "shoe_size": (
            "Talla de calzado",
            "text",
            known("shoe_size", "talla_calzado"),
            [],
        ),
        "color": ("Color", "text", known("color") or "", []),
        "max_items": (
            "Máximo de prendas distintas",
            "select",
            "6",
            [{"value": str(i), "label": str(i)} for i in range(1, 7)],
        ),
        "keep_color": (
            "Color de las alternativas",
            "select",
            "true",
            [
                {"value": "true", "label": "Conservar mis colores"},
                {"value": "false", "label": "Aceptar otros colores"},
            ],
        ),
    }
    defaults = {
        "discover": ["query", "color"],
        "new_arrivals": ["top_size", "bottom_size", "shoe_size"],
        "outfit": ["occasion", "budget", "top_size", "bottom_size", "shoe_size"],
        "branches": ["city"],
        "budget": ["budget", "max_items", "top_size", "bottom_size", "shoe_size"],
        "savings": ["keep_color"],
    }
    values, applied = [], []
    for key in (fields or defaults[goal])[:6]:
        label, kind, value, options = configs[key]
        if value is not None and str(value) != "" and not show_known:
            applied.append(f"{label}: {value}")
            continue
        values.append(
            {
                "key": key,
                "label": label,
                "kind": kind,
                "value": str(value) if value is not None else "",
                "required": not show_known
                or key in {"budget", "city", "occasion", "max_items", "keep_color"},
                "options": options,
            }
        )
    return {
        "type": "shopping_question",
        "title": GOALS[goal][0],
        "source_tool": "ask_shopping_preferences",
        "goal": goal,
        "request": (request or GOALS[goal][1])[:700],
        "fields": values,
        "applied": applied,
        "note": "Revisa y confirma una sola vez. La búsqueda continúa al confirmar; estos datos no cambian tu perfil.",
    }
