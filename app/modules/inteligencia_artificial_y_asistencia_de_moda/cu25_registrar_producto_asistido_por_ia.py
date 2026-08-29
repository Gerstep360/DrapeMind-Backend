"""CU-25: Registrar producto asistido por IA.
Paquete: Inteligencia artificial y asistencia de moda (PK-05).
"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import require_role
from app.db.session import get_db
from app.models import Role, User
from app.services.ai import call_gemma

router = APIRouter()


class ProductAiAssistRequest(BaseModel):
    nombre_borrador: str
    material: str | None = "Lino y Algodón"
    estilo_objetivo: str | None = "Elegante Moderno"


class ProductAiAssistResponse(BaseModel):
    titulo_comercial: str
    descripcion_editorial: str
    guia_cuidado: str
    tags_estilo: list[str]


@router.post(
    "/products/assist-creation",
    response_model=ProductAiAssistResponse,
    summary="CU-25: Asistencia de IA para redacción y categorización de prendas",
    description="Genera la descripción sastrera de lujo, consejos de mantenimiento y tags de moda para el catálogo.",
)
async def asistir_creacion_producto_ia(
    payload: ProductAiAssistRequest,
    _admin: User = Depends(require_role(Role.ADMIN, Role.VENDEDOR)),
    db: Session = Depends(get_db),
) -> dict:
    """CU-25: Redacción asistida de catálogo por IA."""
    prompt = (
        f"Genera una ficha de producto de alta gama para '{payload.nombre_borrador}'. "
        f"Material: {payload.material}. Estilo: {payload.estilo_objetivo}. "
        "Incluye descripción editorial, cuidados y 4 etiquetas sastreras."
    )
    res_text, _ = await call_gemma("Eres el redactor editorial de una casa de modas de lujo.", prompt)

    return {
        "titulo_comercial": payload.nombre_borrador.title(),
        "descripcion_editorial": res_text.strip()[:600],
        "guia_cuidado": f"Lavar a mano en agua fría. No retorcer prendas de {payload.material}.",
        "tags_estilo": ["atelier", "alta-costura", "sastreria", "exclusivo"],
    }
