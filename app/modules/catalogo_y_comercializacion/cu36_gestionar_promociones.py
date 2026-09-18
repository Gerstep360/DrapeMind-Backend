"""CU-36: Gestionar promociones.
Paquete: Catálogo y comercialización (PK-02).
"""
from datetime import datetime, timezone
from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_current_user_optional, require_role
from app.db.session import get_db
from app.models import Promotion, Role, User
from app.schemas.api import Message, PromotionInput, PromotionOut

router = APIRouter()


class PromoValidationRequest(BaseModel):
    codigo: str = Field(min_length=1, max_length=50)
    monto_subtotal: Decimal = Field(default=Decimal("0.00"), ge=0)


class PromoValidationResponse(BaseModel):
    valido: bool
    codigo: str
    mensaje: str
    tipo_descuento: str | None = None
    valor_descuento: Decimal | None = None
    descuento_calculado: Decimal = Decimal("0.00")


@router.get(
    "/promotions",
    response_model=list[PromotionOut],
    summary="CU-36: Listar promociones y descuentos vigentes",
    description="Devuelve el catálogo de promociones y reglas de descuento del atelier.",
)
def listar_promociones(
    activo: bool | None = Query(None, description="Filtrar por estado activo"),
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_current_user_optional),
) -> list[Promotion]:
    """CU-36: Consulta de promociones."""
    query = db.query(Promotion)

    # Si no es personal administrativo, solo ver activas
    is_staff = current_user and current_user.rol in (Role.ADMIN, Role.VENDEDOR, Role.ENCARGADO)
    if not is_staff or activo is True:
        query = query.filter(Promotion.activo == True)
    elif activo is False:
        query = query.filter(Promotion.activo == False)

    return query.order_by(Promotion.created_at.desc()).all()


@router.get(
    "/promotions/{promo_id}",
    response_model=PromotionOut,
    summary="CU-36: Obtener detalle de una promoción",
)
def obtener_promocion(
    promo_id: int,
    db: Session = Depends(get_db),
) -> Promotion:
    promo = db.get(Promotion, promo_id)
    if not promo:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Promoción no encontrada.",
        )
    return promo


@router.post(
    "/promotions",
    response_model=PromotionOut,
    status_code=status.HTTP_201_CREATED,
    summary="CU-36: Crear nueva promoción o regla de descuento",
    description="Permite al administrador configurar descuentos porcentuales o de monto fijo.",
)
def crear_promocion(
    payload: PromotionInput,
    _admin: User = Depends(require_role(Role.ADMIN)),
    db: Session = Depends(get_db),
) -> Promotion:
    codigo_clean = payload.codigo.strip().upper()
    existing = db.query(Promotion).filter(Promotion.codigo == codigo_clean).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Ya existe una promoción con el código '{codigo_clean}'.",
        )

    promo = Promotion(
        codigo=codigo_clean,
        descripcion=payload.descripcion.strip() if payload.descripcion else None,
        tipo_descuento=payload.tipo_descuento,
        valor_descuento=payload.valor_descuento,
        monto_minimo_compra=payload.monto_minimo_compra,
        fecha_inicio=payload.fecha_inicio,
        fecha_fin=payload.fecha_fin,
        limite_usos=payload.limite_usos,
        usos_actuales=0,
        activo=payload.activo,
    )
    db.add(promo)
    db.commit()
    db.refresh(promo)
    return promo


@router.put(
    "/promotions/{promo_id}",
    response_model=PromotionOut,
    summary="CU-36: Actualizar promoción",
    description="Permite modificar fechas, porcentajes o vigencia de la promoción.",
)
def actualizar_promocion(
    promo_id: int,
    payload: PromotionInput,
    _admin: User = Depends(require_role(Role.ADMIN)),
    db: Session = Depends(get_db),
) -> Promotion:
    promo = db.get(Promotion, promo_id)
    if not promo:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Promoción no encontrada.",
        )

    codigo_clean = payload.codigo.strip().upper()
    existing = (
        db.query(Promotion)
        .filter(Promotion.codigo == codigo_clean, Promotion.id != promo_id)
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Ya existe otra promoción con el código '{codigo_clean}'.",
        )

    promo.codigo = codigo_clean
    promo.descripcion = payload.descripcion.strip() if payload.descripcion else None
    promo.tipo_descuento = payload.tipo_descuento
    promo.valor_descuento = payload.valor_descuento
    promo.monto_minimo_compra = payload.monto_minimo_compra
    promo.fecha_inicio = payload.fecha_inicio
    promo.fecha_fin = payload.fecha_fin
    promo.limite_usos = payload.limite_usos
    promo.activo = payload.activo

    db.commit()
    db.refresh(promo)
    return promo


@router.delete(
    "/promotions/{promo_id}",
    response_model=Message,
    summary="CU-36: Eliminar promoción",
    description="Elimina una regla promocional.",
)
def eliminar_promocion(
    promo_id: int,
    _admin: User = Depends(require_role(Role.ADMIN)),
    db: Session = Depends(get_db),
) -> Message:
    promo = db.get(Promotion, promo_id)
    if not promo:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Promoción no encontrada.",
        )

    db.delete(promo)
    db.commit()
    return Message(message="Promoción eliminada exitosamente.")


@router.post(
    "/promotions/validate",
    response_model=PromoValidationResponse,
    summary="CU-36: Validar código promocional",
    description="Verifica la validez y calcula el descuento aplicable sobre un subtotal.",
)
def validar_promocion(
    payload: PromoValidationRequest,
    db: Session = Depends(get_db),
) -> PromoValidationResponse:
    codigo_clean = payload.codigo.strip().upper()
    promo = db.query(Promotion).filter(Promotion.codigo == codigo_clean, Promotion.activo == True).first()

    if not promo:
        return PromoValidationResponse(
            valido=False,
            codigo=codigo_clean,
            mensaje="Código de promoción no encontrado o inactivo.",
        )

    now = datetime.now(timezone.utc)
    if promo.fecha_inicio and promo.fecha_inicio > now:
        return PromoValidationResponse(
            valido=False,
            codigo=codigo_clean,
            mensaje="La promoción aún no ha comenzado.",
        )

    if promo.fecha_fin and promo.fecha_fin < now:
        return PromoValidationResponse(
            valido=False,
            codigo=codigo_clean,
            mensaje="La promoción ha expirado.",
        )

    if promo.limite_usos and promo.usos_actuales >= promo.limite_usos:
        return PromoValidationResponse(
            valido=False,
            codigo=codigo_clean,
            mensaje="La promoción ha alcanzado el límite máximo de usos.",
        )

    if payload.monto_subtotal < promo.monto_minimo_compra:
        return PromoValidationResponse(
            valido=False,
            codigo=codigo_clean,
            mensaje=f"Requiere una compra mínima de Bs {promo.monto_minimo_compra:.2f}.",
        )

    descuento = Decimal("0.00")
    if promo.tipo_descuento == "PORCENTAJE":
        descuento = (payload.monto_subtotal * (promo.valor_descuento / Decimal("100"))).quantize(Decimal("0.01"))
    else:
        descuento = min(promo.valor_descuento, payload.monto_subtotal)

    return PromoValidationResponse(
        valido=True,
        codigo=codigo_clean,
        mensaje="Promoción aplicada con éxito.",
        tipo_descuento=promo.tipo_descuento,
        valor_descuento=promo.valor_descuento,
        descuento_calculado=descuento,
    )
