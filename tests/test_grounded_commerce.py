import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services import nvidia_agent, product_cards
from app.services.ai_errors import AIProviderError
from app.services.grounded_reply import has_commercial_claim


def reply(text):
    return {"choices": [{"message": {"role": "assistant", "content": text}}]}


def call(name, **args):
    return {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": name,
                            "type": "function",
                            "function": {"name": name, "arguments": json.dumps(args)},
                        }
                    ],
                }
            }
        ]
    }


@pytest.mark.asyncio
async def test_fabricated_prices_never_stream_to_client(monkeypatch):
    hallucination = "Hoodie Térmico French Terry. Precio: $usd229. Stock: disponible en showroom principal."
    complete = AsyncMock(side_effect=[reply(hallucination), reply(hallucination)])
    monkeypatch.setattr(nvidia_agent, "complete", complete)
    emit = AsyncMock()
    with pytest.raises(AIProviderError, match="verificar"):
        await nvidia_agent.run_nvidia_agent(
            MagicMock(), SimpleNamespace(id=1), "Novedades", {}, emit
        )
    assert not any(
        c.args[0]["type"] in {"answer_snapshot", "results"}
        for c in emit.await_args_list
    )
    for request in complete.await_args_list:
        if request.kwargs.get("on_text"):
            await request.kwargs["on_text"](hallucination)
    assert not any(c.args[0]["type"] == "answer_snapshot" for c in emit.await_args_list)


@pytest.mark.asyncio
@pytest.mark.parametrize("presentation", ["text", "cards"])
async def test_current_database_price_and_explicit_presentation(
    monkeypatch, presentation
):
    complete = AsyncMock(
        side_effect=[
            call("search_products", query="camisa"),
            call(
                "respond_with_products",
                product_ids=[7],
                presentation=presentation,
                include_stock=True,
            ),
        ]
    )
    monkeypatch.setattr(nvidia_agent, "complete", complete)
    monkeypatch.setattr(
        nvidia_agent, "execute_tool", lambda *args: [{"id": 7, "precio": 999}]
    )
    monkeypatch.setattr(
        nvidia_agent,
        "_cards_from_tool",
        lambda *args: [{"id": 7, "precio": 999, "accion": "AGREGAR"}],
    )
    # The final DB read sees a price updated after the search.
    prices = iter([150, 175])

    def fresh(*args):
        return {
            "id": 7,
            "variante_id": 2,
            "nombre": "Camisa real",
            "precio": next(prices),
            "talla": "M",
            "stock_disponible": 4,
            "accion": "AGREGAR",
        }

    monkeypatch.setattr(nvidia_agent, "_product_card", fresh)
    emit = AsyncMock()
    result = await nvidia_agent.run_nvidia_agent(
        MagicMock(), SimpleNamespace(id=1), "precio", {}, emit
    )
    assert (
        "Bs 175.00" in result["direct_response"]
        and "999" not in result["direct_response"]
    )
    assert "4 unidades" in result["direct_response"]
    assert bool(result["action_items"]) == (presentation == "cards")
    visible = [
        c.args[0] for c in emit.await_args_list if c.args[0]["type"] == "results"
    ]
    assert len(visible) == (1 if presentation == "cards" else 0)
    if visible:
        assert visible[0]["action_items"][0]["precio"] == 175


@pytest.mark.asyncio
async def test_history_ids_do_not_verify_a_price_this_turn(monkeypatch):
    monkeypatch.setattr(
        nvidia_agent,
        "complete",
        AsyncMock(
            side_effect=[
                call("respond_with_products", product_ids=[99]),
                reply("Necesito consultar esa prenda."),
            ]
        ),
    )
    execute = MagicMock()
    monkeypatch.setattr(nvidia_agent, "execute_tool", execute)
    result = await nvidia_agent.run_nvidia_agent(
        MagicMock(), SimpleNamespace(id=1), "su precio", {}, AsyncMock()
    )
    assert "error" in result["composite_sub_tools"][0]["result"]
    assert result["action_items"] == []
    execute.assert_not_called()


def test_price_zero_is_not_replaced_by_untrusted_fallback(monkeypatch):
    monkeypatch.setattr(
        product_cards,
        "get_product_detail",
        lambda *a, **kw: {
            "id": 7,
            "nombre": "Prenda real",
            "precio": 0,
            "variantes": [
                {"id": 2, "activo": True, "stock_disponible": 3, "talla": "M"}
            ],
        },
    )
    card = product_cards._product_card(
        MagicMock(), {"id": 7, "nombre": "Falsa", "precio": 999}
    )
    assert card["precio"] == 0 and card["nombre"] == "Prenda real"


@pytest.mark.asyncio
@pytest.mark.parametrize("presentation", ["text", "cards"])
async def test_simple_query_finishes_in_one_inference_with_explicit_presentation(
    monkeypatch, presentation
):
    completion = AsyncMock(
        return_value=call("search_products", query="camisa", presentation=presentation)
    )
    monkeypatch.setattr(nvidia_agent, "complete", completion)
    execute = MagicMock(return_value=[{"id": 7}])
    monkeypatch.setattr(nvidia_agent, "execute_tool", execute)
    card = {
        "id": 7,
        "variante_id": 2,
        "nombre": "Camisa real",
        "precio": 175,
        "accion": "AGREGAR",
    }
    monkeypatch.setattr(nvidia_agent, "_cards_from_tool", lambda *a: [card])
    monkeypatch.setattr(nvidia_agent, "_product_card", lambda *a: card)
    result = await nvidia_agent.run_nvidia_agent(
        MagicMock(), SimpleNamespace(id=1), "consulta", {}, AsyncMock()
    )
    assert completion.await_count == 1
    assert "presentation" not in execute.call_args.args[1]
    assert bool(result["action_items"]) == (presentation == "cards")
    if presentation == "text":
        assert "Bs 175.00" in result["direct_response"]


@pytest.mark.parametrize(
    "text",
    [
        "$usd229",
        "Bs 389",
        "Precio: 429",
        "3 unidades",
        "disponible en sucursal de La Paz",
    ],
)
def test_commercial_output_gate(text):
    assert has_commercial_claim(text)
