"""CU-24: Aplicar recomendación de IA al carrito.
Paquete: Inteligencia artificial y asistencia de moda (PK-05).
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models import User
from app.schemas.api import CartOut, RecommendationApply
from app.services.ai import apply_recommendation

router = APIRouter()


@router.post(
    "/recommendations/apply",
    response_model=CartOut,
    summary="CU-24: Aplicar recomendación de IA al carrito",
    description="Reemplaza o añade la prenda sugerida al carrito ejecutando validaciones de stock y precio en FastAPI.",
)
def aplicar_recomendacion_carrito(
    payload: RecommendationApply,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """CU-24: Aplica cambio sugerido por Altair."""
    return apply_recommendation(db, user.id, payload.recomendacion_id)
