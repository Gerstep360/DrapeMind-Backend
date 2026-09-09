import asyncio
import json
from contextlib import asynccontextmanager
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from app.models import Role
from app.services import ai
from app.services.ai_tools import ToolContext, execute_tool
from app.api.v1.endpoints import branches, orders
from app.schemas.api import BranchStockInput


def test_production_never_creates_mock_electronic_payment(monkeypatch):
    from app.services import store
    monkeypatch.setattr(store.settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(store.settings, "PAYMENT_PROVIDER", "mock")
    db = MagicMock()
    with pytest.raises(HTTPException) as exc:
        store.create_payment(db, SimpleNamespace(estado="PENDIENTE_PAGO"), "QR")
    assert exc.value.status_code == 503
    db.add.assert_not_called()


@pytest.mark.parametrize("state", ["CANCELADO", "PAGADO", "ENTREGADO"])
def test_payment_cannot_reopen_order_or_double_charge(state):
    from app.services import store
    db = MagicMock()
    payment = SimpleNamespace(estado="PENDIENTE", pedido_id=2)
    db.scalar.side_effect = [payment, SimpleNamespace(estado=state)]
    with pytest.raises(HTTPException) as exc:
        store.confirm_payment(db, "reference", "APROBADO")
    assert exc.value.status_code == 409
    assert payment.estado == "PENDIENTE"
    db.commit.assert_not_called()


def test_expired_reservation_cannot_convert_to_order():
    from datetime import datetime, timedelta, timezone
    from app.services import store
    db = MagicMock()
    db.scalar.return_value = SimpleNamespace(vence_at=datetime.now(timezone.utc) - timedelta(seconds=1))
    with pytest.raises(HTTPException) as exc:
        store.convert_reservation_to_order(db, SimpleNamespace(id=5), 1)
    assert exc.value.status_code == 410
    assert "FOR UPDATE" in str(db.scalar.call_args.args[0])
    db.add.assert_not_called()


def test_expired_reservation_cannot_be_marked_ready(monkeypatch):
    from datetime import datetime, timedelta, timezone
    from fastapi import BackgroundTasks
    from app.api.v1.endpoints import reservations

    db = MagicMock()
    reservation = SimpleNamespace(estado="EN_PREPARACION", sucursal_id=2,
                                  vence_at=datetime.now(timezone.utc) - timedelta(seconds=1))
    db.scalar.return_value = reservation
    monkeypatch.setattr(reservations, "staff_can_access_branch", lambda *_: True)
    expire = MagicMock()
    monkeypatch.setattr(reservations, "expire_due_reservations", expire)
    tasks = BackgroundTasks()
    with pytest.raises(HTTPException) as exc:
        reservations.mark_ready(3, tasks, SimpleNamespace(id=1), db)
    assert exc.value.status_code == 410
    expire.assert_called_once_with(db)
    assert reservation.estado == "EN_PREPARACION"
    db.commit.assert_not_called()
    assert not tasks.tasks


def test_branch_adjustment_flushes_before_total_and_records_actor(monkeypatch):
    db = MagicMock()
    row = SimpleNamespace(stock_total=5, stock_reservado=2, stock_minimo=0, activo=True)
    variant = SimpleNamespace(id=4, producto_id=8)
    db.scalar.side_effect = [variant, row]
    monkeypatch.setattr(branches, "staff_can_access_branch", lambda *_: True)
    def synchronize(session, variant_id):
        session.flush.assert_called()
        assert row.stock_total == 9
    monkeypatch.setattr(branches, "_sync_variant_totals", synchronize)
    monkeypatch.setattr(branches, "_stock_payload", lambda *_: {})
    branches.set_branch_stock(3, BranchStockInput(variante_id=4, stock_total=9),
                              SimpleNamespace(id=6, rol=Role.ENCARGADO), db, "Recepción lote 12")
    movement = db.add.call_args.args[0]
    assert movement.sucursal_id == 3
    assert movement.usuario_id == 6
    assert movement.tipo == "ENTRADA"
    assert movement.cantidad == 4
    assert movement.stock_total_anterior == 5
    assert movement.stock_total_nuevo == 9


def test_budget_uses_exact_prices_and_rejects_duplicate_variants():
    db = MagicMock()
    db.execute.return_value.all.return_value = [
        (SimpleNamespace(id=1, talla="XL", color="Azul", stock_total=3, stock_reservado=1),
         SimpleNamespace(id=5, nombre="Camisa", precio=Decimal("99.90"))),
        (SimpleNamespace(id=2, talla="42", color="Gris", stock_total=1, stock_reservado=1),
         SimpleNamespace(id=6, nombre="Pantalón", precio=Decimal("50.20"))),
    ]
    context = ToolContext(db=db, user=SimpleNamespace(id=7))
    result = execute_tool("calculate_selection_budget", {"variant_ids": [1, 2], "budget": "150.00"}, context)
    assert result["total"] == "150.10"
    assert result["saldo"] == "-0.10"
    assert result["dentro_presupuesto"] is False
    assert result["stock_verificado"] is False
    assert "error" in execute_tool("calculate_selection_budget", {"variant_ids": [1, 1], "budget": "150.00"}, context)


def test_payment_tool_does_not_expose_another_customers_payment():
    db = MagicMock()
    db.scalar.return_value = None
    result = execute_tool("get_my_payment_status", {"order_id": 999}, ToolContext(db=db, user=SimpleNamespace(id=7)))
    assert "error" in result
    db.scalars.assert_not_called()


def test_branch_movements_require_assignment(monkeypatch):
    monkeypatch.setattr(branches, "staff_can_access_branch", lambda *_: False)
    db = MagicMock()
    with pytest.raises(HTTPException) as exc:
        branches.branch_movements(3, 50, SimpleNamespace(id=1, rol=Role.ENCARGADO), db)
    assert exc.value.status_code == 403
    db.scalars.assert_not_called()


def test_receipt_requires_approved_payment():
    db = MagicMock()
    db.get.return_value = SimpleNamespace(usuario_id=7, sucursal_id=2, estado="PENDIENTE_PAGO")
    db.scalars.return_value = []
    with pytest.raises(HTTPException) as exc:
        orders.receipt(8, SimpleNamespace(id=7), db)
    assert exc.value.status_code == 409


def test_socket_calls_real_agent_with_model_selected_new_tool(monkeypatch):
    events = []
    observations = []
    responses = iter([
        {"type": "tool", "tool": "get_my_payment_status", "arguments": {"order_id": 23}, "reason": "Consultar el estado de tu pago"},
        {"type": "finish", "answer": "El pago sigue **pendiente** en el servidor.", "presentation": "text"},
    ])

    async def complete(messages, **kwargs):
        observations.append(messages[-1]["content"])
        return {"choices": [{"message": {"content": json.dumps(next(responses))}}]}

    @asynccontextmanager
    async def lease():
        yield

    async def healthy():
        return True

    async def send(event):
        events.append(event)

    monkeypatch.setattr(ai, "get_ai_session", lambda *_: SimpleNamespace(id=9, resumen_contexto=None))
    monkeypatch.setattr(ai, "_save_interaction", lambda *a, **k: SimpleNamespace(id=11))
    monkeypatch.setattr(ai, "_completion", complete)
    monkeypatch.setattr(ai.model_runtime, "lease", lease)
    monkeypatch.setattr(ai.model_runtime, "is_healthy", healthy)
    monkeypatch.setattr("app.services.ai_agent.execute_tool", lambda name, args, ctx: {"estado": "PENDIENTE"})
    asyncio.run(ai.run_agent_socket(MagicMock(), SimpleNamespace(id=7, nombre="Ana"), "¿Se registró el abono de mi compra 23?", None, send))
    assert len(observations) == 2
    assert any(e.get("name") == "get_my_payment_status" and e["type"] == "tool_start" for e in events)
    assert "pendiente" in "".join(e.get("content", "") for e in events if e["type"] == "token")
