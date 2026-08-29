"""CU-22: Analizar estilo del carrito.
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
    "/cart/style-check",
    response_model=AIResponse,
    summary="CU-22: Evaluar coherencia y estilo del perchero",
    description="Evalúa la combinación cromática, balance y formalidad de las prendas añadidas al carrito.",
)
async def analizar_estilo_carrito(
    payload: CartAnalysisRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """CU-22: Crítica y score de estilo del carrito."""
    return await run_ai_action(db, user, "style", payload.objetivo, payload.sesion_id)
