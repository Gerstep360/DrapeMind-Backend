"""CU-25: Registrar producto asistido por IA real.
Paquete: Inteligencia artificial y asistencia de moda (PK-05).
"""
import json
import re
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
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


# ---------------------------------------------------------
# 1. Esquemas de Entrada y Salida para Asistencia de Prendas
# ---------------------------------------------------------
class ProductAiAssistRequest(BaseModel):
    nombre_borrador: str
    material: str | None = "Lino y Algodón"
    estilo_objetivo: str | None = "Elegante Moderno"


class ProductAiAssistResponse(BaseModel):
    titulo_comercial: str
    descripcion_editorial: str
    guia_cuidado: str
    tags_estilo: list[str]

    @field_validator("tags_estilo", mode="before")
    @classmethod
    def parse_tags(cls, v: Any) -> list[str]:
        if isinstance(v, str):
            return [t.strip().lstrip("#") for t in v.replace(",", " ").split() if t.strip()]
        if isinstance(v, list):
            return [str(t).strip().lstrip("#") for t in v if str(t).strip()]
        return []


class ProductStudioAiContent(BaseModel):
    titulo_comercial: str = Field(description="Título comercial formal de alta gama sastrera")
    descripcion_editorial: str = Field(description="Descripción sastrera de alta costura destacando caída, textura y acabados")
    guia_cuidado: str = Field(description="Instrucciones técnicas de cuidado, lavado y planchado para las fibras textiles")
    tags_estilo: list[str] = Field(description="Entre 4 y 7 etiquetas de estilo, tendencia y tejido")
    silueta_corte: str = Field(description="Definición sastrera del corte y silueta de la prenda")
    precio_sugerido_estimado: Decimal = Field(description="Precio sugerido en Bolivianos (Bs) coherente con el tipo de prenda y confección de lujo")
    categoria_recomendada: str = Field(description="Categoría recomendada más adecuada para la prenda")

    @field_validator("tags_estilo", mode="before")
    @classmethod
    def parse_tags(cls, v: Any) -> list[str]:
        if isinstance(v, str):
            return [t.strip().lstrip("#") for t in v.replace(",", " ").split() if t.strip()]
        if isinstance(v, list):
            return [str(t).strip().lstrip("#") for t in v if str(t).strip()]
        return []

    @field_validator("precio_sugerido_estimado", mode="before")
    @classmethod
    def parse_precio(cls, v: Any) -> Decimal:
        if isinstance(v, (int, float, str)):
            # Limpiar posibles prefijos 'Bs' o comas
            cleaned = str(v).replace("Bs", "").replace("$", "").replace(",", "").strip()
            try:
                return Decimal(cleaned)
            except Exception:
                return Decimal("350.00")
        return v


def _extract_json_payload(text: str) -> dict:
    """Limpia y extrae un diccionario JSON de la respuesta del modelo."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        first_newline = cleaned.find("\n")
        if first_newline != -1:
            cleaned = cleaned[first_newline + 1:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        cleaned = cleaned.strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if match:
            return json.loads(match.group(0))
        raise


# ---------------------------------------------------------
# 2. CU-25 Básico: Redacción asistida de catálogo por IA real
# ---------------------------------------------------------
@router.post(
    "/products/assist-creation",
    response_model=ProductAiAssistResponse,
    summary="CU-25: Asistencia de IA para redacción y categorización de prendas (Básico)",
    description="Genera la descripción sastrera de lujo, consejos de mantenimiento y tags de moda con IA real.",
)
async def asistir_creacion_producto_ia(
    payload: ProductAiAssistRequest,
    _admin: User = Depends(require_role(Role.ADMIN, Role.VENDEDOR)),
    db: Session = Depends(get_db),
) -> ProductAiAssistResponse:
    """CU-25: Redacción asistida de catálogo por IA real en JSON estructurado."""
    system_prompt = (
        "Eres el redactor editorial senior de una casa de modas y sastrería de alta gama. "
        "Genera una ficha de producto sastrero en formato JSON válido según el esquema solicitado. CERO EMOJIS."
    )

    user_prompt = f"""
Datos de la prenda:
- Nombre borrador: {payload.nombre_borrador}
- Material / Tejido: {payload.material or "Fibras de temporada"}
- Estilo objetivo: {payload.estilo_objetivo or "Elegante Moderno"}

Genera la ficha completa en formato JSON con la siguiente estructura exacta:
{{
  "titulo_comercial": "Título de alta costura para la prenda",
  "descripcion_editorial": "Descripción editorial elegante de 2 a 3 oraciones resaltando la caída y corte",
  "guia_cuidado": "Instrucciones precisas de cuidado y conservación textil",
  "tags_estilo": ["tag1", "tag2", "tag3", "tag4"]
}}

REGLAS:
1. Responde ÚNICAMENTE con el objeto JSON válido.
2. CERO EMOJIS.
"""

    try:
        raw_response, _ = await call_gemma(
            system=system_prompt,
            user=user_prompt,
            response_format={"type": "json_object"},
            temperature=0.35,
            max_tokens=600,
        )
        data = _extract_json_payload(raw_response)
        return ProductAiAssistResponse.model_validate(data)
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Error en el motor de inferencia de IA al generar la ficha del producto: {str(exc)}",
        )


# ---------------------------------------------------------
# 3. CU-25 Avanzado: Estudio autónomo de producto asistido por IA
# ---------------------------------------------------------
@router.post(
    "/products/assist-studio",
    response_model=ProductAiAssistExtendedResponse,
    summary="CU-25: Estudio autónomo de redacción y categorización asistida por IA",
    description="Estudio completo para estructurar prendas desde conceptos, fotos o bocetos textiles con IA real.",
)
async def estudio_creacion_producto_ia(
    payload: ProductAiAssistExtendedRequest,
    _admin: User = Depends(require_role(Role.ADMIN, Role.VENDEDOR)),
    db: Session = Depends(get_db),
) -> ProductAiAssistExtendedResponse:
    """CU-25: Estudio de catálogo sastrero autónomo impulsado por IA real."""
    # 1. La BD extrae las categorías disponibles en la plataforma
    cats = db.scalars(select(Category.nombre).where(Category.activo == True).limit(20)).all()
    categorias_disponibles = list(cats) if cats else ["Sacos", "Pantalones", "Vestidos", "Camisas", "Accesorios"]

    # 2. Configuración de modelo y rol
    modelo_choice = payload.modelo_ia or "ALTAIR_MINI"
    if modelo_choice == "ALTAIR_MINI":
        nombre_modelo_usado = "Altair Mini (Scout 0.6B - Inferencia Rápida)"
        system_prompt = (
            "Eres Altair Mini, motor ágil de inteligencia de catálogo sastrero de DrapeMind. "
            "Genera la ficha técnica y comercial completa en formato JSON estricto. CERO EMOJIS."
        )
    elif modelo_choice == "ALTAIR_VARIABLE":
        nombre_modelo_usado = "Altair Variable (Orquestación Híbrida Dinámica)"
        system_prompt = (
            "Eres Altair Variable, diseñador y consultor textil adaptativo de DrapeMind. "
            "Genera la ficha técnica y comercial completa en formato JSON estricto. CERO EMOJIS."
        )
    else:
        nombre_modelo_usado = "Altair Principal (Gemma 4 E2B - Razonamiento Profundo)"
        system_prompt = (
            "Eres Altair Principal, Director Creativo y Maestro Sastre de DrapeMind Atelier. "
            "Genera la ficha técnica y comercial completa con rigor de alta costura en formato JSON estricto. CERO EMOJIS."
        )

    # 3. Contexto ensamblado para la IA
    user_prompt = f"""
Ficha conceptual de la prenda:
- Nombre borrador: {payload.nombre_borrador}
- Material: {payload.material or "Fibras Nobles"}
- Género objetivo: {payload.genero_objetivo or "UNISEX"}
- Estilo objetivo: {payload.estilo_objetivo or "Alta Costura Minimalista"}
- Notas de confección / taller: {payload.detalles_confeccion or "Pieza sastrera de colección"}
- Descripción visual / boceto: {payload.descripcion_imagen or "Sin imagen previa"}
- Categoría sugerida por el usuario: {payload.categoria_sugerida or "Ninguna"}
- Categorías activas en la tienda: {', '.join(categorias_disponibles)}

Genera la estructuración completa de la prenda en formato JSON con la siguiente estructura exacta:
{{
  "titulo_comercial": "Título comercial sastrero de alta gama",
  "descripcion_editorial": "Descripción editorial de 2 o 3 oraciones destacando silueta, caída y confección",
  "guia_cuidado": "Instrucciones técnicas de cuidado textil específicas para el material indicado",
  "tags_estilo": ["tag1", "tag2", "tag3", "tag4", "tag5"],
  "silueta_corte": "Definición del corte y silueta sastrera",
  "precio_sugerido_estimado": 450.00,
  "categoria_recomendada": "Categoría elegida de la lista provista o deducida"
}}

REGLAS OBLIGATORIAS:
1. Responde EXCLUSIVAMENTE con el objeto JSON válido.
2. CERO EMOJIS.
3. El campo 'precio_sugerido_estimado' debe ser un número decimal en Bolivianos (Bs) coherente con el tipo de prenda y materiales de alta calidad.
4. 'categoria_recomendada' debe coincidir preferentemente con una de las categorías activas en la tienda.
"""

    # 4. Inferencia con Structured Output JSON
    try:
        raw_response, _ = await call_gemma(
            system=system_prompt,
            user=user_prompt,
            response_format={"type": "json_object"},
            temperature=0.35,
            max_tokens=900,
        )
        data = _extract_json_payload(raw_response)
        parsed = ProductStudioAiContent.model_validate(data)
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Error en el motor de inferencia de IA al procesar el estudio de la prenda: {str(exc)}",
        )

    # 5. Retornar respuesta estructurada
    return ProductAiAssistExtendedResponse(
        titulo_comercial=parsed.titulo_comercial,
        descripcion_editorial=parsed.descripcion_editorial,
        guia_cuidado=parsed.guia_cuidado,
        tags_estilo=parsed.tags_estilo,
        silueta_corte=parsed.silueta_corte,
        precio_sugerido_estimado=parsed.precio_sugerido_estimado,
        categoria_recomendada=parsed.categoria_recomendada,
        modelo_utilizado=nombre_modelo_usado,
    )
