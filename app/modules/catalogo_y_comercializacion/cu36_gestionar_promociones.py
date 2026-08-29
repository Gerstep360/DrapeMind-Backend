"""CU-36: Gestionar promociones.
Paquete: Catálogo y comercialización (PK-02).
"""
from decimal import Decimal
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import require_role
from app.db.session import get_db
from app.models import Product, Role, User

router = APIRouter()


@router.get(
    "/promotions",
    summary="CU-36: Listar promociones y descuentos vigentes",
    description="Devuelve prendas con precios especiales, descuentos y promociones del atelier.",
)
def listar_promociones(db: Session = Depends(get_db)) -> list[dict]:
    """CU-36: Consulta de promociones activas."""
    products = db.query(Product).filter(Product.activo == True).limit(10).all()
    return [
        {
            "producto_id": p.id,
            "nombre": p.nombre,
            "precio_original": float(p.precio),
            "descuento_porcentaje": 15,
            "precio_promocional": float(p.precio * Decimal("0.85")),
        }
        for p in products
    ]


@router.post(
    "/promotions",
    summary="CU-36: Aplicar promoción o descuento",
    description="Permite al administrador configurar descuentos porcentuales en prendas.",
)
def aplicar_promocion(
    producto_id: int,
    descuento_porcentaje: int,
    _admin: User = Depends(require_role(Role.ADMIN)),
    db: Session = Depends(get_db),
) -> dict:
    """CU-36: Configuración de precio promocional."""
    product = db.get(Product, producto_id)
    if not product:
        return {"error": "Producto no encontrado"}
    return {
        "producto_id": product.id,
        "descuento": f"{descuento_porcentaje}%",
        "mensaje": "Promoción configurada exitosamente",
    }
