from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload
from app.api.deps import get_current_user, get_current_user_optional
from app.db.session import get_db
from app.models import Order, OrderItem, Product, ProductReview, User

router = APIRouter(tags=["CU-30 · Reseñas y calificaciones"])


class ReviewCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    calificacion: int = Field(ge=1, le=5, strict=True)
    titulo: str | None = Field(default=None, max_length=120)
    comentario: str = Field(min_length=3, max_length=1000)


class ReviewOut(BaseModel):
    id: int
    producto_id: int
    usuario_id: int
    calificacion: int
    titulo: str | None = None
    comentario: str
    compra_verificada: bool
    usuario_nombre: str
    creado_en: str
    actualizado_en: str | None = None


class ProductReviewsResponse(BaseModel):
    producto_id: int
    promedio: float
    total: int
    distribucion: dict[str, int]
    resenas: list[ReviewOut]
    mi_resena: ReviewOut | None = None


def product_or_404(db, product_id, *, lock=False):
    statement = select(Product).where(Product.id == product_id, Product.activo.is_(True))
    product = db.scalar(statement.with_for_update() if lock else statement)
    if not product:
        raise HTTPException(404, "Prenda no encontrada")
    return product


def review_out(review, name=None):
    return ReviewOut(
        id=review.id, producto_id=review.producto_id, usuario_id=review.usuario_id,
        calificacion=review.calificacion, titulo=review.titulo,
        comentario=review.comentario, compra_verificada=review.compra_verificada,
        usuario_nombre=name or review.usuario.nombre,
        creado_en=review.created_at.isoformat(),
        actualizado_en=review.updated_at.isoformat() if review.updated_at else None,
    )


@router.get("/products/{product_id}/reviews", response_model=ProductReviewsResponse)
def get_product_reviews(product_id: int, limit: int = Query(50, ge=1, le=100),
                        offset: int = Query(0, ge=0),
                        current_user: User | None = Depends(get_current_user_optional),
                        db: Session = Depends(get_db)):
    product_or_404(db, product_id)
    filters = [ProductReview.producto_id == product_id, ProductReview.activo.is_(True)]
    distribution = {str(i): 0 for i in range(1, 6)}
    for rating, count in db.execute(select(ProductReview.calificacion, func.count())
                                    .where(*filters).group_by(ProductReview.calificacion)):
        distribution[str(rating)] = count
    total = sum(distribution.values())
    rows = db.scalars(select(ProductReview).options(selectinload(ProductReview.usuario))
                      .where(*filters).order_by(ProductReview.id.desc()).offset(offset).limit(limit)).all()
    own = db.scalar(select(ProductReview).where(*filters, ProductReview.usuario_id == current_user.id)) if current_user else None
    return ProductReviewsResponse(
        producto_id=product_id, total=total,
        promedio=round(sum(int(k)*v for k,v in distribution.items())/total, 1) if total else 0,
        distribucion=distribution, resenas=[review_out(row) for row in rows],
        mi_resena=review_out(own, current_user.nombre) if own else None,
    )


@router.post("/products/{product_id}/reviews", response_model=ReviewOut)
def create_or_update_review(product_id: int, payload: ReviewCreate,
                            current_user: User = Depends(get_current_user),
                            db: Session = Depends(get_db)):
    product_or_404(db, product_id, lock=True)
    verified = bool(db.scalar(select(func.count(OrderItem.id)).join(Order, Order.id == OrderItem.pedido_id)
        .where(Order.usuario_id == current_user.id, Order.comprador_registrado.is_(True),
               Order.paid_at.is_not(None), Order.estado.in_(["PAGADO", "PREPARANDO", "LISTO", "ENVIADO", "ENTREGADO"]),
               OrderItem.producto_id == product_id)))
    row = db.scalar(select(ProductReview).where(ProductReview.producto_id == product_id,
                                                ProductReview.usuario_id == current_user.id))
    if not row:
        row = ProductReview(tenant_id=current_user.tenant_id, producto_id=product_id, usuario_id=current_user.id)
        db.add(row)
    row.calificacion = payload.calificacion
    row.titulo = payload.titulo or None
    row.comentario = payload.comentario
    row.compra_verificada = verified
    row.activo = True
    row.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(row)
    return review_out(row, current_user.nombre)


@router.delete("/products/{product_id}/reviews")
def delete_my_review(product_id: int, current_user: User = Depends(get_current_user),
                     db: Session = Depends(get_db)):
    product_or_404(db, product_id, lock=True)
    row = db.scalar(select(ProductReview).where(ProductReview.producto_id == product_id,
                                                ProductReview.usuario_id == current_user.id))
    if not row:
        raise HTTPException(404, "No tienes una reseña para esta prenda")
    db.delete(row)
    db.commit()
    return {"ok": True, "mensaje": "Reseña eliminada"}


@router.get("/products/{product_id}/my-review", response_model=ReviewOut | None)
def get_my_review(product_id: int, current_user: User = Depends(get_current_user),
                   db: Session = Depends(get_db)):
    product_or_404(db, product_id)
    row = db.scalar(select(ProductReview).where(ProductReview.producto_id == product_id,
        ProductReview.usuario_id == current_user.id, ProductReview.activo.is_(True)))
    return review_out(row, current_user.nombre) if row else None
