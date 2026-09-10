"""Versioned, chat-scoped memory. No keyword routing and no permanent user profile."""
import json
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, JsonValue, ValidationError, field_validator

MAX_ENTITIES = 8


class EntityRef(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["product", "order", "reservation", "branch", "cart_item"]
    id: int = Field(gt=0)
    label: str = Field(default="", max_length=100)


class ChatContext(BaseModel):
    model_config = ConfigDict(extra="ignore")
    version: Literal[2] = 2
    constraints: dict[str, JsonValue] = Field(default_factory=dict)
    facts: dict[str, JsonValue] = Field(default_factory=dict)
    selected: list[EntityRef] = Field(default_factory=list, max_length=8)
    recent: list[EntityRef] = Field(default_factory=list, max_length=8)
    previous: list[EntityRef] = Field(default_factory=list, max_length=8)
    pending: str | None = Field(default=None, max_length=240)

    @field_validator("constraints", "facts")
    @classmethod
    def bounded_facts(cls, value):
        if len(value) > 12 or len(json.dumps(value, ensure_ascii=False)) > 1600:
            raise ValueError("Context facts exceed bounded capacity")
        for key, item in value.items():
            if len(key) > 48 or isinstance(item, dict):
                raise ValueError("Use short keys and scalar values or scalar lists")
            if isinstance(item, list) and (len(item) > 8 or any(isinstance(x, (dict, list)) for x in item)):
                raise ValueError("Nested context is not allowed")
        return value


def read_context(memory: dict | None) -> ChatContext:
    # Legacy preference extraction is deliberately not treated as a permanent profile.
    try:
        return ChatContext.model_validate(memory or {})
    except ValidationError:
        return ChatContext()


def update_context(state: ChatContext, patch: dict | None) -> ChatContext:
    """Gemma proposes facts; server validates size and entity provenance."""
    if not isinstance(patch, dict):
        return state
    data = state.model_dump()
    for name in ("constraints", "facts"):
        if isinstance(patch.get(name), dict):
            for key, value in patch[name].items():
                if value is None:
                    data[name].pop(key, None)
                else:
                    data[name][key] = value
    if "pending" in patch:
        data["pending"] = patch["pending"]
    if "selected" in patch:
        known = {(item.type, item.id): item for item in state.recent + state.previous + state.selected}
        selected = []
        for value in patch["selected"] if isinstance(patch["selected"], list) else []:
            if isinstance(value, dict):
                try:
                    reference = EntityRef.model_validate(value)
                except ValidationError:
                    continue
                item = known.get((reference.type, reference.id))
                if item:
                    selected.append(item.model_dump())
        if selected or patch["selected"] == []:
            data["selected"] = selected[:MAX_ENTITIES]
    try:
        return ChatContext.model_validate(data)
    except ValidationError:
        return state


def observe_cards(state: ChatContext, cards: list[dict]) -> ChatContext:
    """Only actual server-rendered cards create referenceable entities, in display order."""
    types = {"AGREGAR": "product", "VER_PEDIDO": "order", "VER_RESERVA": "reservation"}
    entities = []
    seen = set()
    for card in cards:
        kind = types.get(card.get("accion"))
        identity = (kind, card.get("id"))
        if not kind or not isinstance(identity[1], int) or identity[1] <= 0 or identity in seen:
            continue
        seen.add(identity)
        entities.append(EntityRef(type=kind, id=identity[1], label=str(card.get("nombre") or "")[:100]))
    if entities:
        if [(e.type, e.id) for e in state.recent] != [(e.type, e.id) for e in entities[:MAX_ENTITIES]]:
            state.previous = state.recent
        state.recent = entities[:MAX_ENTITIES]
    return state


def prompt_state(state: ChatContext) -> str:
    data = state.model_dump(exclude_defaults=True)
    data.pop("version", None)
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def serialize_observation(value):
    """Column/row packing removes repeated keys, not rows or monetary precision."""
    if isinstance(value, list):
        if value and all(isinstance(row, dict) for row in value):
            columns = sorted(set().union(*(row.keys() for row in value)))
            return {"columns": columns, "rows": [
                [serialize_observation(row.get(key)) for key in columns] for row in value
            ]}
        return [serialize_observation(item) for item in value]
    if isinstance(value, dict):
        return {key: serialize_observation(item) for key, item in value.items()
                if key not in {"imagenes", "imagen", "image_url", "tags_ai", "resumen_texto"}}
    return value
