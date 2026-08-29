"""Paquete 02: Catálogo y comercialización (PK-02).
Casos de uso:
- CU-04: Consultar catálogo de prendas
- CU-05: Buscar y filtrar prendas
- CU-06: Consultar detalle, talla, color y variante
- CU-08: Gestionar favoritos
- CU-29: Gestionar productos de ropa
- CU-30: Gestionar categorías, tallas, colores y variantes
- CU-31: Gestionar temporadas y colecciones
- CU-36: Gestionar promociones
"""
from fastapi import APIRouter

from app.modules.catalogo_y_comercializacion.cu04_consultar_catalogo_de_prendas import router as cu04_router
from app.modules.catalogo_y_comercializacion.cu05_buscar_y_filtrar_prendas import router as cu05_router
from app.modules.catalogo_y_comercializacion.cu06_consultar_detalle_talla_color_y_variante import router as cu06_router
from app.modules.catalogo_y_comercializacion.cu08_gestionar_favoritos import router as cu08_router
from app.modules.catalogo_y_comercializacion.cu29_gestionar_productos_de_ropa import router as cu29_router
from app.modules.catalogo_y_comercializacion.cu30_gestionar_categorias_tallas_colores_y_variantes import router as cu30_router
from app.modules.catalogo_y_comercializacion.cu31_gestionar_temporadas_y_colecciones import router as cu31_router
from app.modules.catalogo_y_comercializacion.cu36_gestionar_promociones import router as cu36_router

catalog_router = cu04_router
catalog_router.include_router(cu06_router)
catalog_router.include_router(cu08_router)
catalog_router.include_router(cu30_router)
catalog_router.include_router(cu31_router)
catalog_router.include_router(cu36_router)

admin_catalog_router = cu29_router
admin_catalog_router.include_router(cu30_router)
admin_catalog_router.include_router(cu31_router)
admin_catalog_router.include_router(cu36_router)


__all__ = ["catalog_router", "admin_catalog_router"]
