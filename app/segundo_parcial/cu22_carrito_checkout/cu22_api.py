from fastapi import APIRouter
from app.segundo_parcial.compartido.reportes import (
    CheckoutConfirmation,
    Depends,
    HTTPException,
    Order,
    Session,
    User,
    get_current_user,
    get_db,
    select,
)

router = APIRouter(prefix="", tags=["CU-22 · carrito_checkout"])


@router.get("/orders/checkout-options")
def checkout_options(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    """Read-only availability of this basket in each authorized company branch."""
    from app.models import Cart, CartItem, Branch, BranchStock
    from app.segundo_parcial.cu23_pagos.cu23_modelos import (
        DeferredPurchase,
        PURCHASE_TERMINAL,
    )
    from app.services.store import get_active_cart

    cart = get_active_cart(db, user.id, create=False)
    items = (
        list(db.scalars(select(CartItem).where(CartItem.carrito_id == cart.id)))
        if cart
        else []
    )
    basket = sorted((item.variante_id, item.cantidad) for item in items)
    pending = db.scalars(
        select(DeferredPurchase).where(
            DeferredPurchase.usuario_id == user.id,
            DeferredPurchase.estado.not_in(PURCHASE_TERMINAL),
        )
    )
    operation = (
        next(
            (
                row.operacion_id
                for row in pending
                if sorted(
                    (i["variante_id"], i["cantidad"]) for i in row.payload["items"]
                )
                == basket
            ),
            None,
        )
        if basket
        else None
    )
    branches = []
    for branch in db.scalars(
        select(Branch).where(Branch.activo.is_(True)).order_by(Branch.id)
    ):
        stocks = {
            s.variante_id: max(0, s.stock_total - s.stock_reservado)
            for s in db.scalars(
                select(BranchStock).where(
                    BranchStock.sucursal_id == branch.id, BranchStock.activo.is_(True)
                )
            )
        }
        missing = [
            {
                "variante_id": i.variante_id,
                "solicitado": i.cantidad,
                "disponible": stocks.get(i.variante_id, 0),
            }
            for i in items
            if stocks.get(i.variante_id, 0) < i.cantidad
        ]
        branches.append(
            {
                "id": branch.id,
                "nombre": branch.nombre,
                "direccion": branch.direccion,
                "disponible": bool(items) and not missing,
                "faltantes": missing,
            }
        )
    return {
        "carrito_id": cart.id if cart else None,
        "vacio": not items,
        "compra_pendiente": operation,
        "sucursales": branches,
    }


@router.get("/commerce/config")
def commerce_config(user: User = Depends(get_current_user)):
    from app.core.config import settings

    return {
        "moneda": "BOB",
        "costo_delivery": str(settings.DELIVERY_FEE_BOB),
        "costo_recojo": "0.00",
    }


@router.get("/orders/checkout-operations/{operation_id}")
def checkout_result(
    operation_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from uuid import UUID

    try:
        value = str(UUID(operation_id))
    except ValueError:
        raise HTTPException(422, "Identificador de confirmación inválido")
    row = db.scalar(
        select(CheckoutConfirmation).where(
            CheckoutConfirmation.usuario_id == user.id,
            CheckoutConfirmation.operacion_id == value,
        )
    )
    if not row:
        raise HTTPException(
            404, "Esta confirmación todavía no tiene un pedido registrado"
        )
    from app.schemas.api import OrderOut

    return OrderOut.model_validate(db.get(Order, row.pedido_id))
