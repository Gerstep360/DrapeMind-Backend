"""CU-31: Gestionar temporadas y colecciones.
Paquete: Catálogo y comercialización (PK-02).
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import require_role
from app.db.session import get_db
from app.models import Category, Role, User

router = APIRouter()


@router.get(
    "/collections",
    summary="CU-31: Consultar temporadas y colecciones vigentes",
    description="Devuelve las colecciones especiales de la marca (ej. Otoño-Invierno, Atelier Gala, Verano Lino).",
)
def listar_colecciones(db: Session = Depends(get_db)) -> list[dict]:
    """CU-31: Consulta pública de colecciones especiales."""
    categories = db.query(Category).filter(Category.activo == True).all()
    return [
        {
            "id": cat.id,
            "nombre": cat.nombre,
            "descripcion": cat.descripcion,
            "es_coleccion": True,
        }
        for cat in categories
    ]


@router.post(
    "/collections",
    summary="CU-31: Crear o activar temporada/colección",
    description="Permite al administrador lanzar una nueva colección de moda.",
)
def crear_coleccion(
    nombre: str,
    descripcion: str | None = None,
    _admin: User = Depends(require_role(Role.ADMIN)),
    db: Session = Depends(get_db),
) -> dict:
    """CU-31: Alta de temporada o colección de temporada."""
    cat = Category(nombre=nombre, descripcion=descripcion, activo=True)
    db.add(cat)
    db.commit()
    db.refresh(cat)
    return {"id": cat.id, "nombre": cat.nombre, "mensaje": "Colección creada con éxito"}
