from fastapi import APIRouter

from app.modules.acceso_y_gestion_de_usuarios import admin_users_router, auth_router, users_router
from app.modules.analitica_y_control import analytics_router
from app.modules.carrito_pedidos_y_pagos import (
    admin_orders_router, cart_router, orders_router, payments_router,
)
from app.modules.catalogo_y_comercializacion import admin_catalog_router, catalog_router
from app.modules.inteligencia_artificial_y_asistencia_de_moda import ai_router, ai_ws_router
from app.modules.realidad_aumentada import ar_router
from app.modules.reservas_y_atencion_en_tienda import (
    admin_reservations_router, reservations_router,
)
from app.modules.sucursales_inventario_y_proveedores import (
    admin_branches_inventory_router, branches_router,
)

api_router = APIRouter()

# PK-01: Acceso y gestión de usuarios
api_router.include_router(auth_router, prefix="/auth", tags=["PK-01: Acceso y gestión de usuarios"])
api_router.include_router(users_router, prefix="/users", tags=["PK-01: Acceso y gestión de usuarios"])

# PK-02: Catálogo y comercialización
api_router.include_router(catalog_router, prefix="/catalog", tags=["PK-02: Catálogo y comercialización"])

# PK-03: Carrito, pedidos y pagos
api_router.include_router(cart_router, prefix="/cart", tags=["PK-03: Carrito, pedidos y pagos"])
api_router.include_router(orders_router, prefix="/orders", tags=["PK-03: Carrito, pedidos y pagos"])
api_router.include_router(payments_router, prefix="/payments", tags=["PK-03: Carrito, pedidos y pagos"])

# PK-04: Reservas y atención en tienda
api_router.include_router(reservations_router, prefix="/reservations", tags=["PK-04: Reservas y atención en tienda"])

# PK-05: Inteligencia artificial y asistencia de moda
api_router.include_router(ai_router, prefix="/ai", tags=["PK-05: Inteligencia artificial y asistencia de moda"])
api_router.include_router(ai_ws_router, prefix="/ws")

# PK-06: Realidad aumentada
api_router.include_router(ar_router, prefix="/ar", tags=["PK-06: Realidad aumentada"])

# PK-07: Sucursales, inventario y proveedores
api_router.include_router(branches_router, prefix="/branches", tags=["PK-07: Sucursales, inventario y proveedores"])

# Endpoints administrativos consolidados de los paquetes (PK-01, PK-02, PK-03, PK-04, PK-07, PK-08)
admin_router = APIRouter()
admin_router.include_router(admin_users_router)
admin_router.include_router(admin_catalog_router)
admin_router.include_router(admin_orders_router)
admin_router.include_router(admin_reservations_router)
admin_router.include_router(admin_branches_inventory_router)
admin_router.include_router(analytics_router)
api_router.include_router(admin_router, prefix="/admin", tags=["Administración, analítica y control"])

