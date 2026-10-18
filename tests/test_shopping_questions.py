from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
import json
import pytest
from app.services.shopping_questions import question_form
from app.services.chat_context import ChatContext, merge_turn_constraints
from app.services import nvidia_agent


PROFILE = {
    "profile": {"presupuesto_habitual": "250", "talla_superior": "M"},
    "city": None,
    "categories": [],
}


def test_preflight_is_registered_on_the_real_modular_router():
    from app.main import app

    assert any(
        getattr(route, "path", "") == "/api/v1/ai/shopping-setup"
        for route in app.routes
    )


def test_form_does_not_repeat_known_fields_and_applies_explicit_conversation_values():
    form = question_form(
        "outfit",
        PROFILE,
        fields=["budget", "top_size", "occasion"],
        constraints={"budget": "500"},
    )
    assert [f["key"] for f in form["fields"]] == ["occasion"]
    assert any("500" in v for v in form["applied"])


def test_preflight_prefills_profile_without_an_inference():
    form = question_form("budget", PROFILE, show_known=True)
    assert next(f["value"] for f in form["fields"] if f["key"] == "budget") == "250"
    assert form["type"] == "shopping_question"


def test_explicit_constraints_survive_next_turn_without_clobbering_parallel_changes():
    original = ChatContext(constraints={"top_size": "M"})
    latest = ChatContext(constraints={"top_size": "M", "city": "Sucre"})
    merged = merge_turn_constraints(
        latest, original, {"constraints": {"top_size": "L"}}
    )
    assert merged.constraints == {"top_size": "L", "city": "Sucre"}


@pytest.mark.asyncio
async def test_native_question_pauses_after_one_call_until_customer_confirms(
    monkeypatch,
):
    call = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "ask",
                            "type": "function",
                            "function": {
                                "name": "ask_shopping_preferences",
                                "arguments": json.dumps(
                                    {"goal": "branches", "fields": ["city"]}
                                ),
                            },
                        }
                    ],
                }
            }
        ]
    }
    complete = AsyncMock(return_value=call)
    monkeypatch.setattr(nvidia_agent, "complete", complete)
    response = await nvidia_agent.run_nvidia_agent(
        MagicMock(),
        SimpleNamespace(id=1),
        "Qué sucursal me conviene",
        {},
        AsyncMock(),
        shopping_profile=PROFILE,
    )
    assert complete.await_count == 1
    assert response["ui_blocks"][0]["type"] == "shopping_question"
    assert response["ui_blocks"][0]["fields"][0]["key"] == "city"
    assert response["action_items"] == []
