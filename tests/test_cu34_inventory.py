from types import SimpleNamespace
from unittest.mock import MagicMock
import pytest
from fastapi import HTTPException

from app.models import Role
from app.schemas.api import BranchStockInput
from app.modules.sucursales_inventario_y_proveedores import cu34_gestionar_inventario_por_sucursal as cu34


def test_assigned_branches_for_admin():
    db = MagicMock()
    admin_user = SimpleNamespace(id=1, rol=Role.ADMIN)
    branch = SimpleNamespace(id=10, ciudad_id=1, codigo="SUC-01", nombre="Sucursal Central", direccion="Av. 1", telefono="123", latitud=None, longitud=None, activo=True)
    city = SimpleNamespace(nombre="La Paz", departamento="La Paz")
    db.execute.return_value = [(branch, city)]

    result = cu34.assigned_branches(admin_user, db)
    assert len(result) == 1
    assert result[0]["nombre"] == "Sucursal Central"
    assert result[0]["ciudad"] == "La Paz"


def test_assigned_branches_for_encargado():
    db = MagicMock()
    encargado = SimpleNamespace(id=2, rol=Role.ENCARGADO)
    branch = SimpleNamespace(id=10, ciudad_id=1, codigo="SUC-01", nombre="Sucursal Norte", direccion="Av. 2", telefono="456", latitud=None, longitud=None, activo=True)
    city = SimpleNamespace(nombre="Cochabamba", departamento="Cochabamba")
    db.execute.return_value = [(branch, city)]

    result = cu34.assigned_branches(encargado, db)
    assert len(result) == 1
    assert result[0]["nombre"] == "Sucursal Norte"


def test_set_branch_stock_allows_encargado_and_records_movement(monkeypatch):
    monkeypatch.setattr(cu34, "staff_can_access_branch", lambda db, user, branch_id: True)
    monkeypatch.setattr(cu34, "_sync_variant_totals", lambda db, var_id: None)

    db = MagicMock()
    branch = SimpleNamespace(id=5, activo=True)
    variant = SimpleNamespace(id=12, producto_id=3, sku="VAR-01", color="Azul", talla="M", activo=True)
    existing_stock = SimpleNamespace(sucursal_id=5, variante_id=12, stock_total=10, stock_reservado=2, stock_minimo=1, activo=True)
    product = SimpleNamespace(id=3, nombre="Vestido Gala", activo=True)

    db.get.side_effect = lambda model, pk: branch if model == cu34.Branch else (product if model == cu34.Product else None)
    db.scalar.side_effect = [variant, existing_stock]

    encargado = SimpleNamespace(id=9, rol=Role.ENCARGADO)
    payload = BranchStockInput(variante_id=12, stock_total=18, stock_minimo=2, activo=True)

    result = cu34.set_branch_stock(5, payload, encargado, db, observacion="Recepción de nuevo lote")
    assert result["stock_total"] == 18
    assert result["stock_reservado"] == 2
    assert result["stock_disponible"] == 16
    db.commit.assert_called_once()
    # Verifica que se haya creado el movimiento de inventario
    db.add.assert_called_once()


def test_set_branch_stock_rejects_unassigned_encargado(monkeypatch):
    monkeypatch.setattr(cu34, "staff_can_access_branch", lambda db, user, branch_id: False)
    db = MagicMock()
    encargado = SimpleNamespace(id=9, rol=Role.ENCARGADO)
    payload = BranchStockInput(variante_id=12, stock_total=20)

    with pytest.raises(HTTPException) as exc:
        cu34.set_branch_stock(5, payload, encargado, db)
    assert exc.value.status_code == 403
    assert "No está asignado a esta sucursal" in exc.value.detail


def test_set_branch_stock_rejects_below_reserved(monkeypatch):
    monkeypatch.setattr(cu34, "staff_can_access_branch", lambda db, user, branch_id: True)
    db = MagicMock()
    branch = SimpleNamespace(id=5, activo=True)
    variant = SimpleNamespace(id=12, producto_id=3)
    existing_stock = SimpleNamespace(sucursal_id=5, variante_id=12, stock_total=10, stock_reservado=8, activo=True)

    db.get.return_value = branch
    db.scalar.side_effect = [variant, existing_stock]

    admin = SimpleNamespace(id=1, rol=Role.ADMIN)
    payload = BranchStockInput(variante_id=12, stock_total=5)  # 5 < 8 reservado

    with pytest.raises(HTTPException) as exc:
        cu34.set_branch_stock(5, payload, admin, db)
    assert exc.value.status_code == 409
    assert "menor al reservado" in exc.value.detail


def test_branch_movements_allows_encargado_assigned(monkeypatch):
    monkeypatch.setattr(cu34, "staff_can_access_branch", lambda db, user, branch_id: True)
    db = MagicMock()
    movement = SimpleNamespace(
        id=1, variante_id=12, sucursal_id=5, tipo="ENTRADA", cantidad=5,
        stock_total_anterior=10, stock_total_nuevo=15, usuario_id=2,
        observacion="Lote recibido", created_at=None,
    )
    db.scalars.return_value = [movement]

    encargado = SimpleNamespace(id=2, rol=Role.ENCARGADO)
    res = cu34.branch_movements(5, 50, encargado, db)
    assert len(res) == 1
    assert res[0]["tipo"] == "ENTRADA"
    assert res[0]["cantidad"] == 5
