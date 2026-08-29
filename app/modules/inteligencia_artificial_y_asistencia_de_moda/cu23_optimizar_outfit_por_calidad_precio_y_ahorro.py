"""CU-23: Optimizar outfit por calidad, precio y ahorro.
Paquete: Inteligencia artificial y asistencia de moda (PK-05).
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models import User
from app.schemas.api import AIResponse, CartAnalysisRequest
from app.services.ai import run_ai_action

router = APIRouter()


@router.post(
    "/cart/value-check",
    response_model=AIResponse,
    summary="CU-23: Optimizar calidad/precio y ahorro",
    description="Compara el costo y materiales de las prendas del carrito y propone alternativas con mejor relación calidad/precio.",
)
async def optimizar_outfit_valor(
    payload: CartAnalysisRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """CU-23: Análisis de ahorro y calidad."""
    return await run_ai_action(db, user, "value", payload.objetivo, payload.sesion_id)
