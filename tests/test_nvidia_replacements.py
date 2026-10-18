from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock
from app.models import Product, ProductVariant
from app.services import ai


def test_observed_alternatives_only_save_same_size_in_stock_savings(monkeypatch):
    db = MagicMock()
    target = SimpleNamespace(
        id=2, activo=True, precio=Decimal("80"), nombre="Camisa alternativa"
    )
    variants = {
        20: SimpleNamespace(
            id=20,
            producto_id=2,
            activo=True,
            stock_total=3,
            stock_reservado=0,
            talla="M",
            color="Azul",
        ),
        21: SimpleNamespace(
            id=21,
            producto_id=2,
            activo=True,
            stock_total=3,
            stock_reservado=0,
            talla="S",
            color="Azul",
        ),
        22: SimpleNamespace(
            id=22,
            producto_id=2,
            activo=True,
            stock_total=1,
            stock_reservado=0,
            talla="M",
            color="Azul",
        ),
    }
    db.get.side_effect = (
        lambda model, identity: variants.get(identity)
        if model is ProductVariant
        else target
        if model is Product and identity == 2
        else None
    )
    cart = {
        "items": [
            {
                "producto_id": 1,
                "variante_id": 10,
                "nombre": "Camisa actual",
                "cantidad": 2,
                "talla": "M",
                "precio_unitario": Decimal("100"),
            }
        ]
    }
    owned_cart = MagicMock(return_value=cart)
    monkeypatch.setattr(ai, "cart_payload", owned_cart)
    candidates = [
        {"product_id": 2, "variant_id": identity} for identity in [20, 21, 22, 20]
    ] + [{"product_id": 999, "variant_id": 20}]
    result = ai._save_replacements(
        db,
        7,
        11,
        [
            {
                "name": "find_alternatives",
                "args": {"product_id": 1},
                "result": candidates,
            }
        ],
    )
    owned_cart.assert_called_once_with(db, 7)
    db.add.assert_called_once()
    record = db.add.call_args.args[0]
    assert record.variante_origen_id == 10 and record.variante_recomendada_id == 20
    assert record.ahorro == Decimal("40")
    assert result[0]["talla"] == "M" and len(result) == 1


def test_alternatives_outside_the_users_cart_are_not_actionable(monkeypatch):
    monkeypatch.setattr(ai, "cart_payload", lambda db, user_id: {"items": []})
    db = MagicMock()
    assert (
        ai._save_replacements(
            db,
            7,
            11,
            [{"name": "find_alternatives", "args": {"product_id": 1}, "result": []}],
        )
        == []
    )
    db.add.assert_not_called()
