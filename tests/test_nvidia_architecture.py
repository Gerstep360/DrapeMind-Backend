import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from pydantic import ValidationError

from app.core.config import Settings, settings
from app.schemas.genui import UIProposal
from app.services import llm_provider, nvidia_agent
from app.services.ai_errors import AIProviderError






@pytest.mark.asyncio
async def test_stream_assembles_native_calls_and_keeps_private_reasoning_hidden(monkeypatch):
    events = [
        {"choices": [{"delta": {"reasoning_content": "private"}}]},
        {"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "c1", "function": {
            "name": "get_store_policy", "arguments": '{"topic":'}}]}}]},
        {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": '"shipping"}'}}]},
                      "finish_reason": "tool_calls"}]},
    ]
    requests = []

    def handle(request):
        requests.append(json.loads(request.content))
        assert request.headers["Authorization"] == "Bearer test"
        data = "".join("data: " + json.dumps(event) + "\n\n" for event in events) + "data: [DONE]\n\n"
        return httpx.Response(200, text=data, headers={"Content-Type": "text/event-stream"})

    original_client = httpx.AsyncClient
    monkeypatch.setattr(settings, "NVIDIA_API_KEY", "test")
    monkeypatch.setattr(llm_provider.httpx, "AsyncClient", lambda **kwargs: original_client(
        **kwargs, transport=httpx.MockTransport(handle)))
    visible = AsyncMock()
    messages = [{"role": "system", "content": "Use tools"}, {"role": "user", "content": "¿Envíos?"}]
    result = await llm_provider.complete(messages, tools=[{"type": "function", "function": {"name": "get_store_policy"}}],
                                         on_text=visible)
    assert json.loads(result["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"]) == {"topic": "shipping"}
    visible.assert_not_called()
    assert requests[0]["messages"] == messages
    assert not {"cache_prompt", "reasoning_budget", "stop"} & requests[0].keys()


@pytest.mark.asyncio
async def test_provider_error_does_not_echo_response_secrets(monkeypatch):
    original_client = httpx.AsyncClient
    monkeypatch.setattr(settings, "NVIDIA_API_KEY", "test")
    monkeypatch.setattr(llm_provider.httpx, "AsyncClient", lambda **kwargs: original_client(
        **kwargs, transport=httpx.MockTransport(lambda _: httpx.Response(401, text="private-api-key"))))
    with pytest.raises(AIProviderError) as error:
        await llm_provider.complete([{"role": "user", "content": "Hola"}])
    assert "401" in str(error.value)
    assert "private-api-key" not in str(error.value)


@pytest.mark.asyncio
async def test_general_conversation_needs_one_inference_no_database_tools(monkeypatch):
    completion = AsyncMock(return_value={"choices": [{"message": {"content": "El algodón es una fibra natural."}}]})
    execute = MagicMock()
    monkeypatch.setattr(nvidia_agent, "complete", completion)
    monkeypatch.setattr(nvidia_agent, "execute_tool", execute)
    result = await nvidia_agent.run_nvidia_agent(MagicMock(), SimpleNamespace(id=7), "¿Qué es el algodón?", {}, AsyncMock())
    assert completion.await_count == 1
    execute.assert_not_called()
    assert result["action_items"] == []
    assert result["direct_response"] == "El algodón es una fibra natural."


@pytest.mark.asyncio
async def test_native_tool_round_trip_and_permissions(monkeypatch):
    calls = [{"id": "c1", "type": "function", "function": {"name": "change_price", "arguments": '{"price":1}'}}]
    completion = AsyncMock(side_effect=[
        {"choices": [{"message": {"role": "assistant", "content": None, "tool_calls": calls}}]},
        {"choices": [{"message": {"content": "No puedo cambiar el precio."}}]},
    ])
    execute = MagicMock()
    monkeypatch.setattr(nvidia_agent, "complete", completion)
    monkeypatch.setattr(nvidia_agent, "execute_tool", execute)
    result = await nvidia_agent.run_nvidia_agent(MagicMock(), SimpleNamespace(id=7), "Cambia el precio", {}, AsyncMock())
    execute.assert_not_called()
    assert "error" in result["composite_sub_tools"][0]["result"]
    sent = completion.await_args_list[1].args[0]
    assert sent[-1]["role"] == "tool"
    assert sent[-1]["tool_call_id"] == "c1"


def test_genui_rejects_arbitrary_code_and_unverified_products():
    with pytest.raises(ValidationError):
        UIProposal.model_validate({"type": "html", "script": "alert(1)"})
    with pytest.raises(ValueError):
        UIProposal(type="product_grid", product_ids=[99]).resolve([])
    block = UIProposal(type="product_grid", product_ids=[3]).resolve([{"id": 3, "accion": "AGREGAR"}])
    assert block["actions"] == ["view_product", "add_to_cart"]


@pytest.mark.asyncio
@pytest.mark.parametrize("available", [True, False])
async def test_onboarding_saves_before_inference_and_reports_real_failure(monkeypatch, available):
    from app.schemas.api import StyleProfileInput
    from app.modules.acceso_y_gestion_de_usuarios.cu03_gestionar_perfil_y_direcciones import guardar_perfil_estilo_me
    from app.services import style_inference
    db = MagicMock()
    profile = SimpleNamespace()
    db.scalar.return_value = profile
    user = SimpleNamespace(id=7, has_style_profile=False)

    async def infer(preferences):
        assert db.commit.call_count == 1
        assert preferences["talla_superior"] == "M"
        if not available:
            raise AIProviderError("Unavailable")
        return "Tu estilo casual combina con siluetas relajadas."

    monkeypatch.setattr(style_inference, "infer_style", infer)
    result = await guardar_perfil_estilo_me(
        StyleProfileInput(talla_superior="M", estilos_preferidos=["casual"], infer_outfit=False, infer_style=True), user, db)
    assert user.has_style_profile
    assert result.completado
    assert result.talla_superior == "M"
    assert bool(result.adn_estilo_ia) == available
    assert bool(result.inferencia_error) != available


def test_launcher_does_not_inherit_destructive_seed_flags(monkeypatch):
    from iniciar_local import child_env
    monkeypatch.setenv("SEED_RESET", "true")
    monkeypatch.setenv("SEED_FORCE", "true")
    env = child_env()
    assert "SEED_RESET" not in env and "SEED_FORCE" not in env
    assert env["ROOT_PATH"] == ""
