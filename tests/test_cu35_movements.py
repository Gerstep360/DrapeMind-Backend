from types import SimpleNamespace
from unittest.mock import MagicMock
import pytest
from fastapi import HTTPException

from app.models import Role
from app.schemas.api import InventoryAdjustment
from app.modules.sucursales_inventario_y_proveedores import (
    cu35_registrar_movimientos_recepcion_y_ajustes_de_inventario as cu35,
)


def test_reception_creates_entrada_movement(monkeypatch):
    monkeypatch.setattr(cu35, "staff_can_access_branch", lambda db, user, branch_id: True)
    monkeypatch.setattr(cu35, "_sync_variant_totals", lambda db, var_id: None)

    db = MagicMock()
    branch = SimpleNamespace(id=2, activo=True)
    variant = SimpleNamespace(id=10, producto_id=1, stock_total=10, stock_reservado=2)
    branch_stock = SimpleNamespace(sucursal_id=2, variante_id=10, stock_total=10, stock_reservado=2)

    db.get.return_value = branch
    db.scalar.side_effect = [variant, branch_stock]

    admin = SimpleNamespace(id=1, rol=Role.ADMIN)
    payload = InventoryAdjustment(
        variante_id=10,
        nuevo_stock_total=25,
        observacion="Recepción de nuevo lote del proveedor",
        sucursal_id=2,
    )

    res = cu35.ajustar_inventario(payload, admin, db)
    assert res["tipo"] == "ENTRADA"
    assert res["cantidad"] == 15
    assert res["stock_anterior"] == 10
    assert res["stock_nuevo"] == 25
    db.add.assert_called_once()
    db.commit.assert_called_once()


def test_reduction_creates_ajuste_movement(monkeypatch):
    monkeypatch.setattr(cu35, "staff_can_access_branch", lambda db, user, branch_id: True)
    monkeypatch.setattr(cu35, "_sync_variant_totals", lambda db, var_id: None)

    db = MagicMock()
    branch = SimpleNamespace(id=2, activo=True)
    variant = SimpleNamespace(id=10, producto_id=1, stock_total=20, stock_reservado=3)
    branch_stock = SimpleNamespace(sucursal_id=2, variante_id=10, stock_total=20, stock_reservado=3)

    db.get.return_value = branch
    db.scalar.side_effect = [variant, branch_stock]

    encargado = SimpleNamespace(id=5, rol=Role.ENCARGADO)
    payload = InventoryAdjustment(
        variante_id=10,
        nuevo_stock_total=14,
        observacion="Ajuste por conteo físico de fin de mes",
        sucursal_id=2,
    )

    res = cu35.ajustar_inventario(payload, encargado, db)
    assert res["tipo"] == "AJUSTE"
    assert res["cantidad"] == 6
    assert res["stock_anterior"] == 20
    assert res["stock_nuevo"] == 14
    db.add.assert_called_once()


def test_encargado_unassigned_rejected(monkeypatch):
    monkeypatch.setattr(cu35, "staff_can_access_branch", lambda db, user, branch_id: False)

    db = MagicMock()
    variant = SimpleNamespace(id=10, stock_reservado=0)
    db.scalar.return_value = variant

    encargado = SimpleNamespace(id=5, rol=Role.ENCARGADO)
    payload = InventoryAdjustment(
        variante_id=10,
        nuevo_stock_total=15,
        observacion="Intento de ajuste en otra sede",
        sucursal_id=99,
    )

    with pytest.raises(HTTPException) as exc:
        cu35.ajustar_inventario(payload, encargado, db)
    assert exc.value.status_code == 403
    assert "No está asignado a esta sucursal" in exc.value.detail


def test_adjustment_below_reserved_rejected(monkeypatch):
    monkeypatch.setattr(cu35, "staff_can_access_branch", lambda db, user, branch_id: True)

    db = MagicMock()
    branch = SimpleNamespace(id=1, activo=True)
    variant = SimpleNamespace(id=10, stock_reservado=5)
    branch_stock = SimpleNamespace(sucursal_id=1, variante_id=10, stock_total=10, stock_reservado=5)

    db.get.return_value = branch
    db.scalar.side_effect = [variant, branch_stock]

    admin = SimpleNamespace(id=1, rol=Role.ADMIN)
    payload = InventoryAdjustment(
        variante_id=10,
        nuevo_stock_total=4,  # Menor que 5 reservado
        observacion="Ajuste inválido por debajo de reserva",
        sucursal_id=1,
    )

    with pytest.raises(HTTPException) as exc:
        cu35.ajustar_inventario(payload, admin, db)
    assert exc.value.status_code == 409
    assert "menor al reservado" in exc.value.detail


def test_listar_movimientos_allows_encargado():
    db = MagicMock()
    movement = SimpleNamespace(
        id=1, variante_id=10, sucursal_id=1, tipo="ENTRADA", cantidad=10,
        stock_total_anterior=5, stock_total_nuevo=15, usuario_id=2,
        observacion="Ingreso de pedido proveedor", created_at=None,
    )
    variant = SimpleNamespace(sku="DRAPE-001", color="Negro", talla="M")
    product = SimpleNamespace(nombre="Pantalón Palazzo")
    branch = SimpleNamespace(nombre="Sucursal Centro")

    db.execute.return_value.all.return_value = [(movement, variant, product, branch)]

    encargado = SimpleNamespace(id=2, rol=Role.ENCARGADO)
    res = cu35.listar_movimientos_inventario(
        tipo="ENTRADA", sucursal_id=None, variante_id=None,
        limit=50, offset=0, staff=encargado, db=db,
    )
    assert len(res) == 1
    assert res[0]["tipo"] == "ENTRADA"
    assert res[0]["sku"] == "DRAPE-001"
    assert res[0]["producto"] == "Pantalón Palazzo"
    assert res[0]["sucursal"] == "Sucursal Centro"
