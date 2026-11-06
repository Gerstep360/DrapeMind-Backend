import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
import pytest
from test_grounded_commerce import call, reply
from app.services import nvidia_agent, ai_tools


@pytest.mark.asyncio
async def test_empty_cart_continues_to_arrivals_before_model_selects_final_cards(
    monkeypatch,
):
    complete = AsyncMock(
        side_effect=[
            call("get_my_cart", presentation="cards"),
            call("get_new_arrivals", limit=2),
            call(
                "respond_with_products",
                product_ids=[7],
                presentation="cards",
                intro="Tu carrito está vacío. Aquí tienes novedades.",
            ),
        ]
    )
    monkeypatch.setattr(nvidia_agent, "complete", complete)
    card = {
        "id": 7,
        "variante_id": 3,
        "precio": 175,
        "nombre": "Camisa real",
        "accion": "AGREGAR",
    }

    def execute(name, args, context):
        return (
            {"estado": "VACIO", "items": []} if name == "get_my_cart" else [{"id": 7}]
        )

    monkeypatch.setattr(nvidia_agent, "execute_tool", execute)
    monkeypatch.setattr(
        nvidia_agent,
        "_cards_from_tool",
        lambda db, name, args, data: [] if name == "get_my_cart" else [card],
    )
    monkeypatch.setattr(nvidia_agent, "_product_card", lambda *args: card)
    emit = AsyncMock()
    result = await nvidia_agent.run_nvidia_agent(
        MagicMock(),
        SimpleNamespace(id=1),
        "Revisa carrito, si está vacío muestra novedades",
        {},
        emit,
    )
    assert complete.await_count == 3
    assert [s["name"] for s in result["composite_sub_tools"]] == [
        "get_my_cart",
        "get_new_arrivals",
        "respond_with_products",
    ]
    assert result["action_items"][0]["precio"] == 175
    assert "carrito está vacío" in result["direct_response"]
    assert sum(c.args[0]["type"] == "results" for c in emit.await_args_list) == 1


@pytest.mark.asyncio
async def test_nonempty_cart_can_finish_without_searching_arrivals(monkeypatch):
    complete = AsyncMock(
        side_effect=[
            call("get_my_cart"),
            call(
                "respond_with_store_data",
                source_tool="get_my_cart",
                presentation="text",
            ),
        ]
    )
    monkeypatch.setattr(nvidia_agent, "complete", complete)
    execute = MagicMock(
        return_value={
            "estado": "CON_PRENDAS",
            "items": [{"producto_id": 7}],
            "resumen_texto": "Camisa real en tu carrito.",
        }
    )
    monkeypatch.setattr(nvidia_agent, "execute_tool", execute)
    monkeypatch.setattr(nvidia_agent, "_cards_from_tool", lambda *args: [])
    result = await nvidia_agent.run_nvidia_agent(
        MagicMock(),
        SimpleNamespace(id=1),
        "Qué tengo en el carrito; si no tengo nada, novedades",
        {},
        AsyncMock(),
    )
    assert {c.args[0] for c in execute.call_args_list} == {"get_my_cart"}
    assert "Camisa real" in result["direct_response"]


@pytest.mark.asyncio
async def test_empty_arrivals_can_trigger_a_different_read_without_intermediate_cards(
    monkeypatch,
):
    complete = AsyncMock(
        side_effect=[
            call("get_new_arrivals"),
            call("get_catalog_overview"),
            call("respond_with_store_data", source_tool="get_catalog_overview"),
        ]
    )
    monkeypatch.setattr(nvidia_agent, "complete", complete)
    monkeypatch.setattr(
        nvidia_agent,
        "execute_tool",
        lambda name, *args: []
        if name == "get_new_arrivals"
        else {
            "tienda": "Tienda actual",
            "productos_activos": 10,
            "productos_con_stock": 6,
            "novedades_con_stock_ultimos_30_dias": 0,
        },
    )
    monkeypatch.setattr(nvidia_agent, "_cards_from_tool", lambda *args: [])
    result = await nvidia_agent.run_nvidia_agent(
        MagicMock(), SimpleNamespace(id=1), "Hay novedades?", {}, AsyncMock()
    )
    assert complete.await_count == 3
    assert "10 productos activos" in result["history_response"]
    assert not result["action_items"]


def test_native_and_mcp_catalog_are_business_schemas_not_presentation_or_skills():
    catalog = ai_tools.tool_catalog()
    assert {tool["name"] for tool in catalog} == {
        name for name, tool in ai_tools.TOOLS.items() if tool.read_only
    }
    assert [tool["name"] for tool in catalog] == sorted(
        tool["name"] for tool in catalog
    )
    assert all(
        "presentation" not in tool["parameters"]["properties"] for tool in catalog
    )
    assert all("tenant_id" not in tool["parameters"]["properties"] for tool in catalog)


def test_arrivals_do_not_apply_hidden_profile_filters(monkeypatch):
    from app.services import personal_shopping

    candidates = MagicMock(return_value=([], None, None, None))
    monkeypatch.setattr(personal_shopping, "_candidates", candidates)
    ai_tools._new_arrivals(MagicMock(), ai_tools.NewArrivalsArgs())
    assert candidates.call_args.args[1].use_profile is False
    ai_tools._new_arrivals(MagicMock(), ai_tools.NewArrivalsArgs(use_profile=True))
    assert candidates.call_args.args[1].use_profile is True
