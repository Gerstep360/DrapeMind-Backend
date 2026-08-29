"""Paquete 05: Inteligencia artificial y asistencia de moda (PK-05).
Casos de uso:
- CU-18: Consultar al asistente inteligente Altair
- CU-19: Buscar prendas mediante lenguaje natural
- CU-20: Generar outfit mediante IA
- CU-21: Completar outfit desde una prenda
- CU-22: Analizar estilo del carrito
- CU-23: Optimizar outfit por calidad, precio y ahorro
- CU-24: Aplicar recomendación de IA al carrito
- CU-25: Registrar producto asistido por IA
- CU-26: Generar reportes empresariales mediante IA
"""
from fastapi import APIRouter

from app.modules.inteligencia_artificial_y_asistencia_de_moda.cu18_consultar_al_asistente_inteligente_altair import (
    router as cu18_router,
    ws_router as cu18_ws_router,
)
from app.modules.inteligencia_artificial_y_asistencia_de_moda.cu19_buscar_prendas_mediante_lenguaje_natural import router as cu19_router
from app.modules.inteligencia_artificial_y_asistencia_de_moda.cu20_generar_outfit_mediante_ia import router as cu20_router
from app.modules.inteligencia_artificial_y_asistencia_de_moda.cu21_completar_outfit_desde_una_prenda import router as cu21_router
from app.modules.inteligencia_artificial_y_asistencia_de_moda.cu22_analizar_estilo_del_carrito import router as cu22_router
from app.modules.inteligencia_artificial_y_asistencia_de_moda.cu23_optimizar_outfit_por_calidad_precio_y_ahorro import router as cu23_router
from app.modules.inteligencia_artificial_y_asistencia_de_moda.cu24_aplicar_recomendacion_de_ia_al_carrito import router as cu24_router
from app.modules.inteligencia_artificial_y_asistencia_de_moda.cu25_registrar_producto_asistido_por_ia import router as cu25_router
from app.modules.inteligencia_artificial_y_asistencia_de_moda.cu26_generar_reportes_empresariales_mediante_ia import router as cu26_router

ai_router = cu18_router
ai_router.include_router(cu19_router)
ai_router.include_router(cu20_router)
ai_router.include_router(cu21_router)
ai_router.include_router(cu22_router)
ai_router.include_router(cu23_router)
ai_router.include_router(cu24_router)
ai_router.include_router(cu25_router)
ai_router.include_router(cu26_router)

ai_ws_router = cu18_ws_router


__all__ = ["ai_router", "ai_ws_router"]
