"""Paquete 07: Sucursales, inventario y proveedores (PK-07).
Casos de uso:
- CU-07: Consultar disponibilidad por sucursal
- CU-28: Gestionar ciudades y sucursales
- CU-32: Gestionar proveedores
- CU-33: Registrar productos y disponibilidad como proveedor
- CU-34: Gestionar inventario por sucursal
- CU-35: Registrar movimientos, recepción y ajustes de inventario
"""
from fastapi import APIRouter

from app.modules.sucursales_inventario_y_proveedores.cu07_consultar_disponibilidad_por_sucursal import router as cu07_router
from app.modules.sucursales_inventario_y_proveedores.cu28_gestionar_ciudades_y_sucursales import router as cu28_router
from app.modules.sucursales_inventario_y_proveedores.cu32_gestionar_proveedores import router as cu32_router
from app.modules.sucursales_inventario_y_proveedores.cu33_registrar_productos_y_disponibilidad_como_proveedor import router as cu33_router
from app.modules.sucursales_inventario_y_proveedores.cu34_gestionar_inventario_por_sucursal import router as cu34_router
from app.modules.sucursales_inventario_y_proveedores.cu35_registrar_movimientos_recepcion_y_ajustes_de_inventario import router as cu35_router

branches_router = cu28_router
branches_router.include_router(cu07_router)
branches_router.include_router(cu34_router)



admin_branches_inventory_router = APIRouter()
admin_branches_inventory_router.include_router(cu32_router)
admin_branches_inventory_router.include_router(cu33_router)
admin_branches_inventory_router.include_router(cu35_router)



__all__ = ["branches_router", "admin_branches_inventory_router"]
