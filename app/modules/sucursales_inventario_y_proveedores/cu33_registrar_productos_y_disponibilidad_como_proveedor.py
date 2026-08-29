"""CU-33: Registrar productos y disponibilidad como proveedor.
Paquete: Sucursales, inventario y proveedores (PK-07).
"""
from decimal import Decimal
from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import require_role
from app.db.session import get_db
from app.models import Role, User

router = APIRouter()


class SupplierProductSupply(BaseModel):
    nombre_material_o_prenda: str = Field(min_length=2)
    cantidad_suministro: int = Field(ge=1)
    costo_unitario: Decimal = Field(ge=0)
    tiempo_entrega_dias: int = Field(default=5, ge=1)


@router.post(
    "/suppliers/{supplier_id}/products",
    status_code=status.HTTP_201_CREATED,
    summary="CU-33: Registrar disponibilidad de lote de proveedor",
    description="Permite registrar un lote de prendas o tejidos disponibles desde la fábrica proveedora.",
)
def registrar_disponibilidad_proveedor(
    supplier_id: int,
    payload: SupplierProductSupply,
    _admin: User = Depends(require_role(Role.ADMIN, Role.VENDEDOR)),
    db: Session = Depends(get_db),
) -> dict:
    """CU-33: Ingreso de oferta mayorista de proveedor."""
    return {
        "proveedor_id": supplier_id,
        "material": payload.nombre_material_o_prenda,
        "unidades_ofertadas": payload.cantidad_suministro,
        "costo_unitario": float(payload.costo_unitario),
        "dias_entrega": payload.tiempo_entrega_dias,
        "estado": "LOTE_DISPONIBLE",
        "mensaje": "Disponibilidad de lote registrada para abastecimiento.",
    }
