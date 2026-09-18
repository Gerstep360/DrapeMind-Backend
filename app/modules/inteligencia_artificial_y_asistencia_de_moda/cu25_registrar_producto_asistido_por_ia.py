"""CU-25: Registrar producto asistido por IA.
Paquete: Inteligencia artificial y asistencia de moda (PK-05).
"""
from decimal import Decimal
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import require_role
from app.db.session import get_db
from app.models import Category, Role, User
from app.schemas.api import (
    ProductAiAssistExtendedRequest,
    ProductAiAssistExtendedResponse,
)
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
    summary="CU-25: Asistencia de IA para redacción y categorización de prendas (Básico)",
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
        "Regla: CERO EMOJIS. Redacta descripción editorial sastrera, cuidados textiles y etiquetas."
    )
    res_text, _ = await call_gemma("Eres el redactor editorial de una casa de modas de lujo. CERO EMOJIS.", prompt)

    clean_text = res_text.strip() if res_text else ""
    if not clean_text or len(clean_text) < 20:
        clean_text = (
            f"Pieza de sastrería contemporánea confeccionada en {payload.material}, con un corte impecable "
            f"diseñado para destacar con distinción sutil en ocasiones de {payload.estilo_objetivo}."
        )

    return {
        "titulo_comercial": payload.nombre_borrador.title(),
        "descripcion_editorial": clean_text[:600],
        "guia_cuidado": f"Lavar en seco o a mano en agua fría con detergente neutro. Secar en sombra y no retorcer fibras de {payload.material}.",
        "tags_estilo": ["atelier", "alta-costura", "sastreria", "diseno-exclusivo"],
    }


@router.post(
    "/products/assist-studio",
    response_model=ProductAiAssistExtendedResponse,
    summary="CU-25: Estudio autónomo de redacción y categorización asistida por IA",
    description="Estudio completo para estructurar prendas desde conceptos, fotos o bocetos textiles con Altair AI.",
)
async def estudio_creacion_producto_ia(
    payload: ProductAiAssistExtendedRequest,
    _admin: User = Depends(require_role(Role.ADMIN, Role.VENDEDOR)),
    db: Session = Depends(get_db),
) -> ProductAiAssistExtendedResponse:
    """CU-25: Asistente autónomo de catálogo para alta costura."""
    material_clean = payload.material or "Fibras Nobles"
    estilo_clean = payload.estilo_objetivo or "Alta Costura Minimalista"
    genero_clean = payload.genero_objetivo or "UNISEX"

    # Contexto de categorías existentes en base de datos para recomendación certera
    cats = db.query(Category.nombre).filter(Category.activo == True).limit(15).all()
    nombres_cats = [c[0] for c in cats] or ["Sacos", "Pantalones", "Vestidos", "Camisas", "Accesorios"]

    # Estimación base de precio sugerido según insumos y nivel de complejidad sastrera
    material_lower = material_clean.lower()
    if any(k in material_lower for k in ["alpaca", "vicuna", "cachemira", "cashmere"]):
        precio_estimado = Decimal("680.00")
        silueta_def = "Corte Imperial con caída estructurada"
    elif any(k in material_lower for k in ["seda", "lino", "pima"]):
        precio_estimado = Decimal("420.00")
        silueta_def = "Silueta fluida con caída natural"
    elif any(k in material_lower for k in ["cuero", "gamuza"]):
        precio_estimado = Decimal("750.00")
        silueta_def = "Corte entallado artesanal"
    else:
        precio_estimado = Decimal("290.00")
        silueta_def = "Corte regular sastrero"

    # Resolver categoría recomendada
    categoria_rec = payload.categoria_sugerida or nombres_cats[0]
    for c in nombres_cats:
        if c.lower() in payload.nombre_borrador.lower():
            categoria_rec = c
            break

    # Prompt sastrero de lujo con instrucción de cero emojis
    prompt = (
        f"Ficha de atelier para la prenda: '{payload.nombre_borrador}'.\n"
        f"Material: {material_clean}. Género: {genero_clean}. Estilo: {estilo_clean}.\n"
        f"Notas de taller: {payload.detalles_confeccion or 'Pieza exclusiva de temporada'}.\n"
        "REGLA CRÍTICA: CERO EMOJIS.\n"
        "Redacta una descripción editorial elegante de máximo 3 oraciones, resaltando el tacto de la tela y el acabado sastrero."
    )

    # Selección y personalización según el modelo de IA elegido
    model_choice = getattr(payload, "modelo_ia", "ALTAIR_MINI") or "ALTAIR_MINI"
    if model_choice == "ALTAIR_MINI":
        nombre_modelo_usado = "Altair Mini (Scout 0.6B)"
        system_prompt = (
            "Eres Altair Mini, redactor ágil de catálogo sastrero de DrapeMind Atelier.\n"
            "REGLAS: CERO EMOJIS. Descripción directa, comercial, precisa y de lectura rápida (máximo 2 oraciones)."
        )
    elif model_choice == "ALTAIR_VARIABLE":
        nombre_modelo_usado = "Altair Variable (Híbrido)"
        system_prompt = (
            "Eres Altair Variable, motor adaptativo de catálogo de DrapeMind Atelier.\n"
            "REGLAS: CERO EMOJIS. Estilo moderno, dinámico y equilibrado entre elegancia y practicidad textil."
        )
    else:
        nombre_modelo_usado = "Altair Principal (Gemma 4 E2B)"
        system_prompt = (
            "Eres Altair Principal, Director Creativo y Redactor Sastrero de DrapeMind Atelier.\n"
            "REGLAS:\n"
            "1. CERO EMOJIS: Jamás uses emojis ni caracteres especiales decorativos.\n"
            "2. Tono: Lujo silencioso, sobrio, técnico y sofisticado.\n"
            "3. Precisión en tejidos y confección."
        )

    editorial_text = ""
    try:
        res_text, _ = await call_gemma(system_prompt, prompt)
        editorial_text = res_text.strip() if res_text else ""
    except Exception:
        editorial_text = ""

    if not editorial_text or len(editorial_text) < 25:
        editorial_text = (
            f"Exclusiva prenda de autor confeccionada en {material_clean}, diseñada para ofrecer una silueta "
            f"armoniosa y confort supremo. Cada detalle de costura refleja la excelencia sastrera del atelier, "
            f"convirtiéndola en un básico atemporal de estética {estilo_clean.lower()}."
        )

    # Guía de cuidado técnica personalizada
    if "alpaca" in material_lower or "lana" in material_lower:
        care_guide = "Limpieza profesional en seco recomendada. Si se lava a mano, usar agua templada sin frotar y secar extendido en horizontal."
    elif "seda" in material_lower:
        care_guide = "Lavar exclusivamente en seco o a mano con jabón líquido suave. Planchar por el revés a baja temperatura sin vapor directo."
    elif "lino" in material_lower:
        care_guide = "Lavado suave a 30°C. No centrifugar intensamente; planchar mientras la tela permanezca ligeramente húmeda para preservar su textura."
    else:
        care_guide = f"Lavar a mano en agua fría con detergente para prendas delicadas. Evitar retorcer y no usar secadora automática para proteger las fibras de {material_clean}."

    # Tags de estilo inteligentes
    tags = [
        "atelier",
        material_clean.split()[0].lower(),
        genero_clean.lower(),
        "sastreria-lujo",
        "edicion-limitada",
    ]

    return ProductAiAssistExtendedResponse(
        titulo_comercial=payload.nombre_borrador.title(),
        descripcion_editorial=editorial_text[:650],
        guia_cuidado=care_guide,
        tags_estilo=tags,
        silueta_corte=silueta_def,
        precio_sugerido_estimado=precio_estimado,
        categoria_recomendada=categoria_rec,
        modelo_utilizado=nombre_modelo_usado,
    )
