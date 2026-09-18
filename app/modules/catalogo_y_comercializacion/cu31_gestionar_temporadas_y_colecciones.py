"""CU-31: Gestionar temporadas y colecciones.
Paquete: Catálogo y comercialización (PK-02).
"""
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import require_role
from app.db.session import get_db
from app.models import Role, Season, User
from app.schemas.api import Message, SeasonInput, SeasonOut

router = APIRouter()


@router.get(
    "/collections",
    response_model=list[SeasonOut],
    summary="CU-31: Consultar temporadas y colecciones vigentes",
    description="Devuelve las colecciones y temporadas de moda activas del atelier.",
)
def listar_colecciones(
    activo: bool | None = Query(None, description="Filtrar por estado activo"),
    db: Session = Depends(get_db),
) -> list[Season]:
    """CU-31: Consulta de temporadas y colecciones."""
    query = db.query(Season)
    if activo is not None:
        query = query.filter(Season.activo == activo)
    return query.order_by(Season.created_at.desc()).all()


@router.get(
    "/collections/{season_id}",
    response_model=SeasonOut,
    summary="CU-31: Obtener detalle de una temporada/colección",
)
def obtener_coleccion(
    season_id: int,
    db: Session = Depends(get_db),
) -> Season:
    season = db.get(Season, season_id)
    if not season:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Temporada o colección no encontrada.",
        )
    return season


@router.post(
    "/collections",
    response_model=SeasonOut,
    status_code=status.HTTP_201_CREATED,
    summary="CU-31: Crear o activar temporada/colección",
    description="Permite al administrador lanzar una nueva colección de moda.",
)
def crear_coleccion(
    payload: SeasonInput,
    _admin: User = Depends(require_role(Role.ADMIN)),
    db: Session = Depends(get_db),
) -> Season:
    """CU-31: Alta de temporada o colección."""
    codigo_clean = payload.codigo.strip().upper()
    existing = db.query(Season).filter(Season.codigo == codigo_clean).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Ya existe una temporada con el código '{codigo_clean}'.",
        )

    season = Season(
        nombre=payload.nombre.strip(),
        codigo=codigo_clean,
        descripcion=payload.descripcion.strip() if payload.descripcion else None,
        fecha_inicio=payload.fecha_inicio,
        fecha_fin=payload.fecha_fin,
        activo=payload.activo,
    )
    db.add(season)
    db.commit()
    db.refresh(season)
    return season


@router.put(
    "/collections/{season_id}",
    response_model=SeasonOut,
    summary="CU-31: Actualizar temporada o colección",
    description="Permite modificar fechas de lanzamiento, nombre o vigencia.",
)
def actualizar_coleccion(
    season_id: int,
    payload: SeasonInput,
    _admin: User = Depends(require_role(Role.ADMIN)),
    db: Session = Depends(get_db),
) -> Season:
    season = db.get(Season, season_id)
    if not season:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Temporada o colección no encontrada.",
        )

    codigo_clean = payload.codigo.strip().upper()
    existing = (
        db.query(Season)
        .filter(Season.codigo == codigo_clean, Season.id != season_id)
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Ya existe otra temporada con el código '{codigo_clean}'.",
        )

    season.nombre = payload.nombre.strip()
    season.codigo = codigo_clean
    season.descripcion = payload.descripcion.strip() if payload.descripcion else None
    season.fecha_inicio = payload.fecha_inicio
    season.fecha_fin = payload.fecha_fin
    season.activo = payload.activo

    db.commit()
    db.refresh(season)
    return season


@router.delete(
    "/collections/{season_id}",
    response_model=Message,
    summary="CU-31: Eliminar temporada o colección",
    description="Elimina una colección del catálogo.",
)
def eliminar_coleccion(
    season_id: int,
    _admin: User = Depends(require_role(Role.ADMIN)),
    db: Session = Depends(get_db),
) -> Message:
    season = db.get(Season, season_id)
    if not season:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Temporada o colección no encontrada.",
        )

    db.delete(season)
    db.commit()
    return Message(message="Temporada o colección eliminada exitosamente.")
