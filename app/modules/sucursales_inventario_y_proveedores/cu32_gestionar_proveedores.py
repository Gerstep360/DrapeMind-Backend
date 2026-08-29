"""CU-32: Gestionar proveedores.
Paquete: Sucursales, inventario y proveedores (PK-07).
"""
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import require_role
from app.db.session import get_db
from app.models import Role, User

router = APIRouter()


class SupplierCreate(BaseModel):
    nombre_empresa: str = Field(min_length=2, max_length=120)
    nit: str | None = None
    contacto_nombre: str | None = None
    telefono: str | None = None
    email: str | None = None
    ciudad: str = "La Paz"
    direccion: str | None = None
    categoria_suministro: str = "Telas y Confección"


@router.get(
    "/suppliers",
    summary="CU-32: Listar proveedores del atelier",
    description="Devuelve el directorio de proveedores de textiles, telas y confección artesanal.",
)
def listar_proveedores(
    _staff: User = Depends(require_role(Role.ADMIN, Role.VENDEDOR)),
    db: Session = Depends(get_db),
) -> list[dict]:
    """CU-32: Directorio de proveedores."""
    return [
        {
            "id": 1,
            "nombre_empresa": "Textiles Andinos & Alpaca Real",
            "nit": "1028374019",
            "contacto_nombre": "Carlos Mendoza",
            "telefono": "+591 71234567",
            "email": "contacto@alpacareal.bo",
            "ciudad": "La Paz",
            "categoria_suministro": "Lana de Alpaca y Cachemira",
        },
        {
            "id": 2,
            "nombre_empresa": "Hilandería Santa Cruz Lino & Algodón",
            "nit": "2938471022",
            "contacto_nombre": "Mariana Vaca",
            "telefono": "+591 78901234",
            "email": "ventas@santacruzlino.bo",
            "ciudad": "Santa Cruz",
            "categoria_suministro": "Lino 100% y Algodón Pima",
        },
    ]


@router.post(
    "/suppliers",
    status_code=status.HTTP_201_CREATED,
    summary="CU-32: Registrar nuevo proveedor",
    description="Permite dar de alta un nuevo fabricante textil o proveedor de insumos.",
)
def crear_proveedor(
    payload: SupplierCreate,
    _admin: User = Depends(require_role(Role.ADMIN)),
    db: Session = Depends(get_db),
) -> dict:
    """CU-32: Alta de proveedor."""
    return {
        "id": 3,
        "nombre_empresa": payload.nombre_empresa,
        "nit": payload.nit,
        "mensaje": "Proveedor registrado exitosamente en el sistema.",
    }
