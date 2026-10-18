from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
import json

import pytest
from pydantic import ValidationError
from app.schemas.genui import UIProposal
from app.services import nvidia_agent
from app.services.ui_presentations import tool_presentation


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
@pytest.mark.parametrize("presentation", ["auto", "text"])
async def test_native_query_selects_prefab_with_server_owned_data(
    monkeypatch, presentation
):
    result = {
        "ranking": [
            {
                "product_id": 7,
                "name": "Camisa real",
                "price_bob": 175,
                "quality_level": 3,
            }
        ]
    }
    monkeypatch.setattr(
        nvidia_agent,
        "complete",
        AsyncMock(
            side_effect=[
                call("compare_products", product_ids=[7, 8]),
                call(
                    "respond_with_store_data",
                    source_tool="compare_products",
                    presentation=presentation,
                ),
            ]
        ),
    )
    monkeypatch.setattr(nvidia_agent, "execute_tool", MagicMock(return_value=result))
    monkeypatch.setattr(nvidia_agent, "_cards_from_tool", lambda *a: [])
    response = await nvidia_agent.run_nvidia_agent(
        MagicMock(), SimpleNamespace(id=1), "Compara estas prendas", {}, AsyncMock()
    )
    assert response["action_items"] == []
    assert "Bs 175.00" in response["history_response"]
    if presentation == "auto":
        assert response["ui_blocks"][0]["type"] == "data_table"
        assert response["ui_blocks"][0]["rows"][0] == {
            "name": "Camisa real",
            "price": "Bs 175.00",
            "quality": "3",
        }
        assert "175" not in response["direct_response"]
    else:
        assert response["ui_blocks"] == []
        assert "Bs 175.00" in response["direct_response"]


@pytest.mark.asyncio
async def test_model_cannot_present_unobserved_tool_or_supply_its_own_rows(monkeypatch):
    with pytest.raises(ValidationError):
        UIProposal.model_validate(
            {
                "type": "tool_result",
                "source_tool": "compare_products",
                "rows": [{"price": 999}],
            }
        )
    monkeypatch.setattr(
        nvidia_agent,
        "complete",
        AsyncMock(
            side_effect=[
                call("present_ui", type="tool_result", source_tool="compare_products"),
                {
                    "choices": [
                        {
                            "message": {
                                "content": "Necesito consultar las prendas primero."
                            }
                        }
                    ]
                },
            ]
        ),
    )
    response = await nvidia_agent.run_nvidia_agent(
        MagicMock(), SimpleNamespace(id=1), "Compara", {}, AsyncMock()
    )
    assert response["ui_blocks"] == []
    assert "error" in response["composite_sub_tools"][0]["result"]


def test_budget_view_uses_calculated_amounts_and_stock_result():
    block = tool_presentation(
        "calculate_selection_budget",
        {
            "total": "375.50",
            "presupuesto": "500",
            "saldo": "124.50",
            "stock_verificado": False,
        },
    )
    assert [m["value"] for m in block["metrics"]] == [
        "Bs 375.50",
        "Bs 500.00",
        "Bs 124.50",
    ]
    assert "sin stock" in block["note"]


def test_stock_does_not_invent_a_branch_and_missing_policy_is_explicit():
    stock = tool_presentation(
        "get_stock",
        [{"product": "Camisa", "color": "Negro", "size": "M", "available": 0}],
    )
    assert stock["rows"] == [
        {
            "name": "Camisa",
            "variant": "Negro · Talla M",
            "available": "0",
            "location": "",
        }
    ]
    assert "Dirección" not in [column["label"] for column in stock["columns"]]
    policy = tool_presentation(
        "get_store_policy", {"topic": "shipping", "configured": False, "policy": None}
    )
    assert policy["tone"] == "notice" and "todavía no configuró" in policy["body"]


def test_empty_orders_have_no_fictitious_records_or_write_actions():
    block = tool_presentation("get_my_orders", [])
    assert block["items"] == [] and block["route"] == "/orders"
    assert "actions" not in block
