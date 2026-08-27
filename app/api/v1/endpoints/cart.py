from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models import User
from app.schemas.api import (
    CartBatchInput,
    CartItemInput,
    CartItemUpdate,
    CartOut,
    CartReplaceInput,
)
from app.services.store import (
    add_cart_item,
    add_cart_items_batch,
    cart_payload,
    delete_cart_item,
    replace_cart_item,
    replace_cart_items_batch,
    update_cart_item,
)

router = APIRouter()


@router.get("", response_model=CartOut, summary="Consultar carrito", description="CU-12/CU-16/CU-17. Retorna el carrito activo y valida precios/stock desde servidor.")
def get_cart(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    return cart_payload(db, current_user.id)


@router.post("/items", response_model=CartOut, status_code=201, summary="Agregar producto al carrito")
def add_item(
    payload: CartItemInput, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> dict:
    return add_cart_item(db, current_user.id, payload.variante_id, payload.cantidad)


@router.post(
    "/items/batch",
    response_model=CartOut,
    status_code=201,
    summary="Agregar outfit completo al carrito",
    description=(
        "Valida todas las variantes y su stock dentro de una sola transacción. "
        "Si una prenda falla, no agrega ninguna."
    ),
)
def add_items_batch(
    payload: CartBatchInput,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    return add_cart_items_batch(
        db,
        current_user.id,
        [(item.variante_id, item.cantidad) for item in payload.items],
    )


@router.put(
    "/items/batch",
    response_model=CartOut,
    summary="Usar una selección de IA como carrito completo",
    description=(
        "Valida todas las variantes y su stock antes de reemplazar el carrito activo. "
        "Si una prenda falla, conserva íntegramente el carrito anterior."
    ),
)
def replace_items_batch(
    payload: CartBatchInput,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    return replace_cart_items_batch(
        db,
        current_user.id,
        [(item.variante_id, item.cantidad) for item in payload.items],
    )


@router.patch("/items/{item_id}", response_model=CartOut, summary="Cambiar cantidad")
def update_item(
    item_id: int, payload: CartItemUpdate, current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    return update_cart_item(db, current_user.id, item_id, payload.cantidad)


@router.delete("/items/{item_id}", response_model=CartOut, summary="Eliminar item")
def remove_item(
    item_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> dict:
    return delete_cart_item(db, current_user.id, item_id)


@router.post(
    "/replace", response_model=CartOut, summary="Reemplazar item de forma segura",
    description="CU-14. Tool controlado: revalida propiedad del carrito, precio y stock antes de aplicar IA.",
)
def replace_item(
    payload: CartReplaceInput, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> dict:
    return replace_cart_item(db, current_user.id, payload.item_id, payload.nueva_variante_id)
