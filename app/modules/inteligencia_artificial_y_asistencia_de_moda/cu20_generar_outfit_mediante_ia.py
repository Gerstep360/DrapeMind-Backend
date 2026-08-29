"""CU-20: Generar outfit mediante IA.
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
    "/outfits/generate",
    response_model=AIResponse,
    summary="CU-20: Generar outfit completo por IA",
    description="Diseña un look integral (superior, inferior, calzado y accesorios) según la ocasión y presupuesto.",
)
async def generar_outfit_ia(
    payload: OutfitRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """CU-20: Generación de outfit completo."""
    message = payload.ocasion + (f". Preferencias: {payload.preferencias}" if payload.preferencias else "")
    return await run_ai_action(db, user, "outfit", message, payload.sesion_id, payload.presupuesto_max)
