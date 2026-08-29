"""CU-19: Buscar prendas mediante lenguaje natural.
Paquete: Inteligencia artificial y asistencia de moda (PK-05).
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models import User
from app.schemas.api import AIResponse, NaturalSearchRequest
from app.services.ai import run_ai_action

router = APIRouter()


@router.post(
    "/search",
    response_model=AIResponse,
    summary="CU-19: Búsqueda semántica en lenguaje natural",
    description="Gemma extrae la intención de compra y características para ejecutar una búsqueda SQL segura y contextual.",
)
async def busqueda_lenguaje_natural(
    payload: NaturalSearchRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """CU-19: Búsqueda con extracción de intención por IA."""
    return await run_ai_action(db, user, "search", payload.consulta, payload.sesion_id)
