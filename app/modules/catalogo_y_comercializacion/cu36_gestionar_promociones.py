"""CU-36: Gestionar promociones.
Paquete: Catálogo y comercialización (PK-02).
"""
from datetime import datetime, timezone
from decimal import Decimal
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_current_user_optional, require_role
from app.db.session import get_db
from app.models import Product, Promotion, Role, User
from app.schemas.api import Message, PromotionInput, PromotionOut
from app.services.realtime import event_hub

router = APIRouter()


class PromoValidationRequest(BaseModel):
    codigo: str = Field(min_length=1, max_length=50)
    monto_subtotal: Decimal = Field(default=Decimal("0.00"), ge=0)
    item_producto_ids: list[int] = Field(default_factory=list)


class PromoValidationResponse(BaseModel):
    valido: bool
    codigo: str
    mensaje: str
    tipo_descuento: str | None = None
    valor_descuento: Decimal | None = None
    descuento_calculado: Decimal = Decimal("0.00")
    producto_id: int | None = None
    producto_nombre: str | None = None


def _serialize_promo(db: Session, promo: Promotion) -> dict:
    data = {
        "id": promo.id,
        "codigo": promo.codigo,
        "descripcion": promo.descripcion,
        "tipo_descuento": promo.tipo_descuento,
        "valor_descuento": promo.valor_descuento,
        "monto_minimo_compra": promo.monto_minimo_compra,
        "fecha_inicio": promo.fecha_inicio,
        "fecha_fin": promo.fecha_fin,
        "limite_usos": promo.limite_usos,
        "usos_actuales": promo.usos_actuales,
        "producto_id": promo.producto_id,
        "producto_nombre": None,
        "producto_imagen": None,
        "activo": promo.activo,
        "created_at": promo.created_at,
        "updated_at": promo.updated_at,
    }
    if promo.producto_id:
        prod = db.get(Product, promo.producto_id)
        if prod:
            data["producto_nombre"] = prod.nombre
            data["producto_imagen"] = prod.imagen_principal or (prod.imagenes[0] if prod.imagenes else None)
    return data


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
) -> list[dict]:
    """CU-36: Consulta de promociones."""
    query = db.query(Promotion)

    is_staff = current_user and current_user.rol in (Role.ADMIN, Role.VENDEDOR, Role.ENCARGADO)
    if not is_staff or activo is True:
        query = query.filter(Promotion.activo == True)
    elif activo is False:
        query = query.filter(Promotion.activo == False)

    promos = query.order_by(Promotion.created_at.desc()).all()
    return [_serialize_promo(db, p) for p in promos]


@router.get(
    "/promotions/{promo_id}",
    response_model=PromotionOut,
    summary="CU-36: Obtener detalle de una promoción",
)
def obtener_promocion(
    promo_id: int,
    db: Session = Depends(get_db),
) -> dict:
    promo = db.get(Promotion, promo_id)
    if not promo:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Promoción no encontrada.",
        )
    return _serialize_promo(db, promo)


@router.post(
    "/promotions",
    response_model=PromotionOut,
    status_code=status.HTTP_201_CREATED,
    summary="CU-36: Crear nueva promoción o regla de descuento",
    description="Permite al administrador configurar descuentos porcentuales, directos de prenda o compra mínima.",
)
def crear_promocion(
    payload: PromotionInput,
    background_tasks: BackgroundTasks,
    _admin: User = Depends(require_role(Role.ADMIN)),
    db: Session = Depends(get_db),
) -> dict:
    codigo_clean = payload.codigo.strip().upper()
    existing = db.query(Promotion).filter(Promotion.codigo == codigo_clean).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Ya existe una promoción con el código '{codigo_clean}'.",
        )

    if payload.producto_id:
        prod = db.get(Product, payload.producto_id)
        if not prod:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"La prenda con ID {payload.producto_id} no existe.",
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
        producto_id=payload.producto_id,
        activo=payload.activo,
    )
    db.add(promo)
    db.commit()
    db.refresh(promo)

    serialized = _serialize_promo(db, promo)

    # Notificar a usuarios conectados mediante WebSockets
    background_tasks.add_task(
        event_hub.publish,
        {
            "type": "promotion_created",
            "promo_id": promo.id,
            "codigo": promo.codigo,
            "descripcion": promo.descripcion,
            "tipo_descuento": promo.tipo_descuento,
            "valor_descuento": float(promo.valor_descuento),
            "producto_nombre": serialized.get("producto_nombre"),
        },
    )
    from app.services.push_notifications import dispatch_notification
    background_tasks.add_task(
        dispatch_notification,
        db,
        None,
        f"Nueva Promoción: {promo.codigo}",
        promo.descripcion or f"Disfruta de descuentos exclusivos en Atelier DrapeMind.",
        "PROMOCION",
        {"screen": "/catalog", "promo_codigo": promo.codigo},
    )


    return serialized


@router.put(
    "/promotions/{promo_id}",
    response_model=PromotionOut,
    summary="CU-36: Actualizar promoción",
    description="Permite modificar fechas, porcentajes, prenda asociada o vigencia.",
)
def actualizar_promocion(
    promo_id: int,
    payload: PromotionInput,
    _admin: User = Depends(require_role(Role.ADMIN)),
    db: Session = Depends(get_db),
) -> dict:
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

    if payload.producto_id:
        prod = db.get(Product, payload.producto_id)
        if not prod:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"La prenda con ID {payload.producto_id} no existe.",
            )

    promo.codigo = codigo_clean
    promo.descripcion = payload.descripcion.strip() if payload.descripcion else None
    promo.tipo_descuento = payload.tipo_descuento
    promo.valor_descuento = payload.valor_descuento
    promo.monto_minimo_compra = payload.monto_minimo_compra
    promo.fecha_inicio = payload.fecha_inicio
    promo.fecha_fin = payload.fecha_fin
    promo.limite_usos = payload.limite_usos
    promo.producto_id = payload.producto_id
    promo.activo = payload.activo

    db.commit()
    db.refresh(promo)
    return _serialize_promo(db, promo)


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
    summary="CU-36: Validar código promocional u oferta",
    description="Verifica la validez y calcula el descuento aplicable sobre un subtotal o prenda vinculada.",
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
            mensaje="Código o regla de promoción no encontrado o inactivo.",
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

    # Validar prenda vinculada
    prod_name = None
    if promo.producto_id:
        prod = db.get(Product, promo.producto_id)
        prod_name = prod.nombre if prod else f"Prenda #{promo.producto_id}"
        if payload.item_producto_ids and promo.producto_id not in payload.item_producto_ids:
            return PromoValidationResponse(
                valido=False,
                codigo=codigo_clean,
                mensaje=f"Esta promoción aplica exclusivamente a la prenda: '{prod_name}'. No se encuentra en el carrito.",
                producto_id=promo.producto_id,
                producto_nombre=prod_name,
            )

    # Validar compra mínima en bolivianos
    if promo.monto_minimo_compra > Decimal("0.00") and payload.monto_subtotal < promo.monto_minimo_compra:
        return PromoValidationResponse(
            valido=False,
            codigo=codigo_clean,
            mensaje=f"Requiere una compra mínima de Bs {promo.monto_minimo_compra:.2f}.",
            producto_id=promo.producto_id,
            producto_nombre=prod_name,
        )

    descuento = Decimal("0.00")
    if promo.tipo_descuento == "PORCENTAJE":
        descuento = (payload.monto_subtotal * (promo.valor_descuento / Decimal("100"))).quantize(Decimal("0.01"))
    elif promo.tipo_descuento == "DOS_POR_UNO":
        descuento = (payload.monto_subtotal * Decimal("0.50")).quantize(Decimal("0.01"))
    else:  # MONTO_FIJO o COMPRA_MINIMA
        descuento = min(promo.valor_descuento, payload.monto_subtotal)

    return PromoValidationResponse(
        valido=True,
        codigo=codigo_clean,
        mensaje="Promoción aplicada con éxito.",
        tipo_descuento=promo.tipo_descuento,
        valor_descuento=promo.valor_descuento,
        descuento_calculado=descuento,
        producto_id=promo.producto_id,
        producto_nombre=prod_name,
    )
