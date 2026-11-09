from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.api.deps import get_current_user
from app.db.session import get_db
from app.models import Cart, CartItem, User
from app.schemas.api import CartItemInput, CartOut
from app.services.saas import require_active_subscription
from app.services.store import get_active_cart, cart_payload, replace_cart_items_batch

router = APIRouter(tags=['CU-22 · Carrito descargado'])


class CartDraftInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    base_items: list[CartItemInput] = Field(max_length=50)
    items: list[CartItemInput] = Field(max_length=50)


def basket(items):
    quantities = {}
    for variant, quantity in items:
        quantities[variant] = quantities.get(variant, 0) + quantity
    return sorted(quantities.items())


@router.put('/cart/draft', response_model=CartOut)
def synchronize_cart_draft(payload: CartDraftInput, user: User = Depends(get_current_user),
                           db: Session = Depends(get_db)):
    require_active_subscription(db, user.tenant_id, 'offline')
    db.scalar(select(User).where(User.id==user.id).with_for_update())
    cart=get_active_cart(db,user.id)
    db.scalar(select(Cart).where(Cart.id==cart.id).with_for_update())
    current=basket(db.execute(select(CartItem.variante_id,CartItem.cantidad).where(CartItem.carrito_id==cart.id)).all())
    base=basket((i.variante_id,i.cantidad) for i in payload.base_items)
    desired=basket((i.variante_id,i.cantidad) for i in payload.items)
    if any(quantity>20 for _,quantity in desired):
        raise HTTPException(422,'Cada variante admite hasta 20 unidades en el carrito')
    if current==desired:
        return cart_payload(db,user.id)
    if current!=base:
        raise HTTPException(409,{'code':'CART_CHANGED','message':'Tu carrito cambió en otro dispositivo. Revisa las dos selecciones antes de continuar.'})
    return replace_cart_items_batch(db,user.id,desired)
