"""CU-08: Gestionar favoritos.
Paquete: Catálogo y comercialización (PK-02).
"""
from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models import Favorite, Product, User
from app.schemas.api import ProductOut

router = APIRouter()


@router.get("/favorites", response_model=list[ProductOut], summary="CU-08: Listar favoritos")
def listar_favoritos(
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> list[Product]:
    return list(
        db.scalars(
            select(Product)
            .join(Favorite, Favorite.producto_id == Product.id)
            .where(Favorite.usuario_id == current_user.id, Product.activo.is_(True))
            .order_by(Favorite.created_at.desc())
        )
    )


@router.post("/favorites/{product_id}", status_code=201, summary="CU-08: Agregar favorito")
def agregar_favorito(
    product_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> dict:
    if not db.get(Product, product_id):
        raise HTTPException(404, "Producto no encontrado")
    db.add(Favorite(usuario_id=current_user.id, producto_id=product_id))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
    return {"message": "Producto agregado a favoritos"}


@router.delete("/favorites/{product_id}", status_code=204, summary="CU-08: Eliminar favorito")
def eliminar_favorito(
    product_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> Response:
    favorite = db.scalar(
        select(Favorite).where(
            Favorite.usuario_id == current_user.id, Favorite.producto_id == product_id
        )
    )
    if favorite:
        db.delete(favorite)
        db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
