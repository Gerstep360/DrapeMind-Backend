import asyncio
import json
from types import SimpleNamespace
from unittest.mock import MagicMock
import pytest
from fastapi import HTTPException
from app.services.chat_context import ChatContext, EntityRef, read_context, update_context, observe_cards, prompt_state, serialize_observation
from app.services.context_prompt import build_messages, prompt_sections
from app.services.chat_sessions import delete_chat, select_product
from app.services.ai_memory import load_ai_memory, build_session_summary
from app.services.ai_agent import run_gemma_tool_agent
from app.main import app


def test_chats_do_not_share_mutable_state():
    a, b = ChatContext(), ChatContext()
    a = update_context(a, {"constraints": {"budget": 500, "purpose": "cena"}})
    assert b.constraints == {}
    assert read_context(load_ai_memory(build_session_summary("", a.model_dump()))).constraints == a.constraints
    assert read_context(None).recent == []


def test_ordered_references_keep_last_and_previous_lists():
    state = observe_cards(ChatContext(), [{"accion": "AGREGAR", "id": i, "nombre": str(i)} for i in [83, 12, 47]])
    state = update_context(state, {"selected": [{"type": "product", "id": 12}]})
    assert state.selected[0].id == 12
    state = observe_cards(state, [{"accion": "AGREGAR", "id": 94, "nombre": "Otra"}])
    assert [x.id for x in state.previous] == [83, 12, 47]
    assert [x.id for x in state.recent] == [94]


def test_generic_constraints_can_change_and_be_removed():
    state = update_context(ChatContext(), {"constraints": {"texture": ["liso", "mate"], "deadline_minutes": 60}})
    state = update_context(state, {"constraints": {"texture": None, "deadline_minutes": 20}})
    assert state.constraints == {"deadline_minutes": 20}
    assert update_context(state, {"facts": {"a": {"nested": "not allowed"}}}) == state


def test_model_cannot_introduce_unobserved_entity():
    state = update_context(ChatContext(), {"selected": [{"type": "product", "id": 777}]})
    assert not state.selected


def test_packing_preserves_all_rows_and_precise_values():
    rows = [{"id": n, "precio": "99.90"} for n in range(17)]
    packed = serialize_observation(rows)
    assert len(packed["rows"]) == 17
    assert packed["columns"] == ["id", "precio"]
    assert packed["rows"][-1] == [16, "99.90"]


def test_prefix_is_stable_and_user_message_is_intact():
    catalog = [{"name": "b", "parameters": {"properties": {}}}, {"name": "a", "parameters": {"properties": {}}}]
    user = "  Mensaje íntegro\ncon detalles  "
    a = prompt_sections(user, ChatContext(), catalog, [])
    b = prompt_sections("Otro", ChatContext(constraints={"style": "libre"}), list(reversed(catalog)), [])
    assert a["system"] == b["system"]
    assert a["tools"] == b["tools"]
    assert build_messages(a)[1]["content"].endswith(user)
    assert "Usuario:" not in a["state"]


def test_active_routes_include_context_lifecycle():
    paths = app.openapi()["paths"]
    assert "delete" in paths["/api/v1/ai/sessions/{session_id}"]
    assert "post" in paths["/api/v1/ai/sessions/{session_id}/selection"]


def test_delete_checks_owner_before_mutating():
    db = MagicMock()
    db.scalar.return_value = None
    with pytest.raises(HTTPException) as exc:
        delete_chat(db, 4, 6)
    assert exc.value.status_code == 404
    db.delete.assert_not_called()
    assert "usuario_id" in str(db.scalar.call_args.args[0])


def test_picker_rejects_product_from_another_chat():
    db = MagicMock()
    db.scalar.return_value = SimpleNamespace(estado="ACTIVA", resumen_contexto=None)
    with pytest.raises(HTTPException) as exc:
        select_product(db, 4, 6, 999)
    assert exc.value.status_code == 409
    db.get.assert_not_called()


def test_picker_updates_only_the_requested_session():
    a = ChatContext(recent=[EntityRef(type="product", id=37, label="Prenda")], pending="¿Hay stock en la sucursal?")
    session = SimpleNamespace(estado="ACTIVA", resumen_contexto=build_session_summary("", a.model_dump()))
    db = MagicMock()
    db.scalar.return_value = session
    db.get.return_value = SimpleNamespace(activo=True, nombre="Camisa")
    result = select_product(db, 4, 6, 37)
    assert result["followup"] == a.pending
    saved = read_context(load_ai_memory(session.resumen_contexto))
    assert saved.selected[0].id == 37
    db.commit.assert_called_once()


def test_agent_uses_model_context_and_picker_without_keyword_rules(monkeypatch):
    from app.services import ai_agent
    monkeypatch.setattr(ai_agent, "tool_catalog", lambda: [])
    memory = ChatContext(recent=[EntityRef(type="product", id=47, label="Lino")]).model_dump()
    async def complete(messages, **kwargs):
        assert "Lino" in messages[1]["content"]
        return {"choices": [{"message": {"content": json.dumps({
            "type": "finish", "answer": "¿Cuál prefieres?", "ui": "product_picker",
            "context": {"constraints": {"fabric_preference": "suave"}, "pending": "Revisa disponibilidad"}
        })}}]}
    result = asyncio.run(run_gemma_tool_agent(MagicMock(), SimpleNamespace(id=4), "Consulta libre", memory, complete))
    assert result["chat_context"]["constraints"] == {"fabric_preference": "suave"}
    assert result["response_meta"]["product_picker"][0]["id"] == 47


def test_history_text_is_not_stored_twice_in_v2_context():
    value = build_session_summary("Mensaje muy privado", ChatContext().model_dump())
    assert "Mensaje muy privado" not in value
