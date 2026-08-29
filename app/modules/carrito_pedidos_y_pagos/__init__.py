"""Paquete 03: Carrito, pedidos y pagos (PK-03).
Casos de uso:
- CU-09: Gestionar carrito o perchero
- CU-10: Realizar checkout y seleccionar entrega o recojo
- CU-11: Procesar y confirmar pago electrónico
- CU-12: Consultar pedidos e historial de compras
- CU-37: Registrar venta presencial, pago y comprobante
- CU-39: Gestionar pedidos, ventas y entregas
"""
from fastapi import APIRouter

from app.modules.carrito_pedidos_y_pagos.cu09_gestionar_carrito_o_perchero import router as cu09_router
from app.modules.carrito_pedidos_y_pagos.cu10_realizar_checkout_y_seleccionar_entrega_o_recojo import router as cu10_router
from app.modules.carrito_pedidos_y_pagos.cu11_procesar_y_confirmar_pago_electronico import router as cu11_router
from app.modules.carrito_pedidos_y_pagos.cu12_consultar_pedidos_e_historial_de_compras import router as cu12_router
from app.modules.carrito_pedidos_y_pagos.cu37_registrar_venta_presencial_pago_y_comprobante import router as cu37_router
from app.modules.carrito_pedidos_y_pagos.cu39_gestionar_pedidos_ventas_y_entregas import router as cu39_router

cart_router = cu09_router

orders_router = cu12_router
orders_router.include_router(cu10_router)

payments_router = cu11_router

admin_orders_router = APIRouter()
admin_orders_router.include_router(cu37_router)
admin_orders_router.include_router(cu39_router)

__all__ = ["cart_router", "orders_router", "payments_router", "admin_orders_router"]
