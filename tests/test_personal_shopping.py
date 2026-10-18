from decimal import Decimal
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, AsyncMock
import json

import pytest
from app.models import Product, ProductVariant, Category, Branch, City, BranchStock
from app.services import personal_shopping as shop, nvidia_agent
from app.services.ai_tools import ToolContext, _evaluate_fit, EvaluateGarmentFitArgs


def product(identity, price):
    return Product(
        id=identity,
        categoria_id=1,
        nombre=f"Camisa {identity}",
        precio=Decimal(price),
        genero_objetivo="UNISEX",
        calidad_nivel=3,
        imagenes=[],
        activo=True,
    )


def variant(identity, product_id, size="M", stock=10):
    return ProductVariant(
        id=identity,
        producto_id=product_id,
        talla=size,
        color="Negro",
        stock_total=stock,
        stock_reservado=0,
        activo=True,
    )


@pytest.fixture
def context(monkeypatch):
    monkeypatch.setattr(
        shop,
        "shopping_context",
        lambda *a: {
            "profile": {
                "talla_superior": "M",
                "talla_inferior": "40",
                "talla_calzado": "42",
                "colores_favoritos": ["Negro"],
                "presupuesto_habitual": "300",
            },
            "city": "La Paz",
        },
    )
    return ToolContext(MagicMock(), SimpleNamespace(id=7), preferences={})


def test_explicit_overrides_conversation_then_profile_without_writing_profile(context):
    context.preferences = {"top_size": "L", "budget": "200"}
    assert shop._preferences(context, shop.DiscoverArgs())["top_size"] == "L"
    actual = shop._preferences(
        context, shop.MoreForLessArgs(top_size="XL", budget="500")
    )
    assert actual["top_size"] == "XL" and actual["budget"] == Decimal("500")
    assert actual["max_price"] == Decimal("500")
    ignored = shop._preferences(context, shop.DiscoverArgs(use_profile=False))
    assert ignored["top_size"] is None and ignored["max_price"] is None
    context.db.commit.assert_not_called()


def test_exact_saved_size_is_used_and_unavailable_size_is_never_substituted(context):
    p = product(1, "90")
    context.db.execute.return_value = [
        (p, variant(1, 1, "XL"), Category(nombre="Camisas")),
        (p, variant(2, 1, "M"), Category(nombre="Camisas")),
    ]
    context.db.scalars.return_value = []
    rows, *_ = shop._candidates(context, shop.DiscoverArgs())
    assert rows[0]["variante_id"] == 2
    assert "colores favoritos" in rows[0]["motivo"]
    context.db.execute.return_value = [
        (p, variant(1, 1, "XL"), Category(nombre="Camisas"))
    ]
    assert shop._candidates(context, shop.DiscoverArgs())[0] == []
    assert (
        shop._candidates(context, shop.DiscoverArgs(size="XL"))[0][0]["talla"] == "XL"
    )


def test_shoe_size_uses_footwear_preference_not_pants_size(context):
    p = product(2, "90")
    p.nombre = "Zapato"
    context.db.execute.return_value = [
        (p, variant(1, 2, "40"), Category(nombre="Calzado")),
        (p, variant(2, 2, "42"), Category(nombre="Calzado")),
    ]
    context.db.scalars.return_value = []
    assert shop._candidates(context, shop.DiscoverArgs())[0][0]["talla"] == "42"


def test_new_arrival_notice_requires_a_real_recent_catalog_date(context):
    p = product(1, "90")
    context.db.execute.return_value = [(p, variant(1, 1), Category(nombre="Camisas"))]
    context.db.scalars.return_value = []
    p.created_at = datetime.now(timezone.utc) - timedelta(days=100)
    assert not shop._candidates(context, shop.DiscoverArgs())[0][0]["is_recent"]
    p.created_at = datetime.now(timezone.utc) - timedelta(days=2)
    assert shop._candidates(context, shop.DiscoverArgs())[0][0]["is_recent"]


@pytest.mark.parametrize("budget, count, total", [("100", 2, "99.99"), ("0", 0, "0")])
def test_more_items_uses_decimal_and_never_exceeds_budget(
    context, monkeypatch, budget, count, total
):
    rows = [
        {"id": 1, "precio": "40.00"},
        {"id": 2, "precio": "59.99"},
        {"id": 3, "precio": "60.00"},
    ]
    monkeypatch.setattr(
        shop,
        "_candidates",
        lambda *a, **k: (rows, {"budget": Decimal(budget)}, [], False, []),
    )
    result = shop.plan_more(context, shop.MoreForLessArgs())
    assert result["item_count"] == count and Decimal(result["total"]) == Decimal(total)
    assert Decimal(result["total"]) <= Decimal(result["budget"])
    context.db.commit.assert_not_called()


def test_no_saved_budget_requires_question_instead_of_guess(context, monkeypatch):
    monkeypatch.setattr(
        shop, "_candidates", lambda *a, **k: ([], {"budget": None}, [], False, [])
    )
    assert "error" in shop.plan_more(context, shop.MoreForLessArgs())


def test_cart_savings_preserves_quantities_and_funds_extras_from_real_difference(
    context, monkeypatch
):
    origin, replacement = product(1, "100"), product(2, "60")
    original_variant, alternative_variant = variant(1, 1), variant(2, 2)
    monkeypatch.setattr(
        shop,
        "cart_payload",
        lambda *a: {"items": [{"producto_id": 1, "variante_id": 1, "cantidad": 2}]},
    )
    context.db.get.side_effect = [origin, original_variant]
    context.db.execute.return_value = [(replacement, alternative_variant)]
    monkeypatch.setattr(
        shop,
        "_candidates",
        lambda *a, **k: (
            [shop._record(product(3, "50"), variant(3, 3), ["Talla M disponible"])],
            {},
            [],
            False,
            [],
        ),
    )
    result = shop.cart_savings(context, shop.CartSavingsArgs())
    assert result["before"] == "200" and result["after"] == "120"
    assert result["saving"] == "80" and result["changes"][0]["quantity"] == 2
    assert result["total_with_extras"] == "170" and result["remaining"] == "30"
    context.db.commit.assert_not_called()


def test_branch_coverage_checks_quantities_and_does_not_invent_distance(
    context, monkeypatch
):
    monkeypatch.setattr(
        shop, "cart_payload", lambda *a: {"items": [{"variante_id": 1, "cantidad": 2}]}
    )
    context.db.scalars.side_effect = [
        [1],
        [
            BranchStock(sucursal_id=1, variante_id=1, stock_total=1, stock_reservado=0),
            BranchStock(sucursal_id=2, variante_id=1, stock_total=2, stock_reservado=0),
        ],
    ]
    context.db.execute.return_value = [
        (Branch(id=1, nombre="Centro", direccion="Real 1"), City(nombre="La Paz")),
        (Branch(id=2, nombre="Sur", direccion="Real 2"), City(nombre="Sucre")),
    ]
    result = shop.branch_advice(context, shop.BranchAdviceArgs())
    assert result["branches"][0]["id"] == 2 and result["branches"][0]["complete"]
    assert not result["branches"][1]["complete"]
    assert "distance" not in result["branches"][0]


def test_fit_tool_does_not_invent_garment_or_body_measurements(context):
    context.db.get.return_value = product(1, "100")
    result = _evaluate_fit(context, EvaluateGarmentFitArgs(product_id=1))
    assert result["pecho_prenda_cm"] is None and result["pecho_usuario_cm"] is None
    assert result["holgura_cm"] is None


@pytest.mark.asyncio
async def test_native_personal_query_uses_profile_context_persists_explicit_size_and_prefab(
    monkeypatch, context
):
    tool = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "a",
                            "type": "function",
                            "function": {
                                "name": "discover_for_me",
                                "arguments": json.dumps(
                                    {"size": "XL", "size_group": "upper"}
                                ),
                            },
                        }
                    ],
                }
            }
        ]
    }
    complete = AsyncMock(return_value=tool)
    monkeypatch.setattr(nvidia_agent, "complete", complete)
    data = {
        "products": [],
        "criteria": ["Talla solicitada: XL"],
        "missing_sizes": [],
        "recent_days": None,
        "note": "Datos reales",
    }
    monkeypatch.setattr(nvidia_agent, "execute_tool", MagicMock(return_value=data))
    response = await nvidia_agent.run_nvidia_agent(
        context.db,
        context.user,
        "Esta vez talla XL",
        {},
        AsyncMock(),
        shopping_profile={"profile": {"talla_superior": "M"}},
    )
    assert response["chat_context"]["constraints"]["top_size"] == "XL"
    assert response["ui_blocks"][0]["type"] == "shopping_summary"
    assert "SHOPPING_PROFILE" in complete.call_args.args[0][0]["content"]
    assert response["action_items"] == []
