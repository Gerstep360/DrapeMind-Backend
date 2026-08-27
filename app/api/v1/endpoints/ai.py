from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models import User
from app.schemas.api import (
    AIRequest, AIResponse, CartAnalysisRequest, CartOut, NaturalSearchRequest,
    OutfitRequest, RecommendationApply,
)
from app.services.ai import apply_recommendation, run_ai_action

router = APIRouter()


@router.post(
    "/chat", response_model=AIResponse, summary="Asistente conversacional",
    description="CU-08. FastAPI obtiene carrito/catalogo mediante tools y entrega a Gemma solo contexto autorizado.",
)
async def chat(
    payload: AIRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> dict:
    return await run_ai_action(db, user, "chat", payload.mensaje, payload.sesion_id)


@router.post(
    "/search", response_model=AIResponse, summary="Busqueda en lenguaje natural",
    description="CU-09. Gemma extrae intencion; search_products ejecuta la consulta controlada y parametrizada.",
)
async def natural_search(
    payload: NaturalSearchRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> dict:
    return await run_ai_action(db, user, "search", payload.consulta, payload.sesion_id)


@router.post("/outfits/generate", response_model=AIResponse, summary="Generar outfit con IA")
async def generate_outfit(
    payload: OutfitRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> dict:
    message = payload.ocasion + (f". Preferencias: {payload.preferencias}" if payload.preferencias else "")
    return await run_ai_action(db, user, "outfit", message, payload.sesion_id, payload.presupuesto_max)


@router.post("/outfits/complete", response_model=AIResponse, summary="Completar outfit desde una prenda")
async def complete_outfit(
    payload: OutfitRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> dict:
    return await run_ai_action(
        db, user, "complete", payload.ocasion, payload.sesion_id,
        payload.presupuesto_max, payload.producto_base_id,
    )


@router.post("/cart/style-check", response_model=AIResponse, summary="Analizar estilo del carrito")
async def style_check(
    payload: CartAnalysisRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> dict:
    return await run_ai_action(db, user, "style", payload.objetivo, payload.sesion_id)


@router.post(
    "/cart/value-check", response_model=AIResponse, summary="Optimizar calidad/precio",
    description="CU-13. La comparacion y ahorro se calculan deterministicamente; Gemma solo explica.",
)
async def value_check(
    payload: CartAnalysisRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> dict:
    return await run_ai_action(db, user, "value", payload.objetivo, payload.sesion_id)


@router.post(
    "/recommendations/apply", response_model=CartOut, summary="Aplicar recomendacion",
    description="CU-14. replace_cart_item vuelve a validar usuario, stock y precio dentro de FastAPI.",
)
def apply(
    payload: RecommendationApply, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> dict:
    return apply_recommendation(db, user.id, payload.recomendacion_id)
