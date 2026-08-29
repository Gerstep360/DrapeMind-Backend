"""CU-21: Completar outfit desde una prenda.
Paquete: Inteligencia artificial y asistencia de moda (PK-05).
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models import User
from app.schemas.api import AIResponse, OutfitRequest
from app.services.ai import run_ai_action

router = APIRouter()


@router.post(
    "/outfits/complete",
    response_model=AIResponse,
    summary="CU-21: Completar outfit a partir de una prenda base",
    description="Sugiere piezas complementarias que combinan sastreramente con una prenda seleccionada por el usuario.",
)
async def completar_outfit_ia(
    payload: OutfitRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """CU-21: Complementar outfit desde pieza base."""
    return await run_ai_action(
        db,
        user,
        "complete",
        payload.ocasion,
        payload.sesion_id,
        payload.presupuesto_max,
        payload.producto_base_id,
    )
