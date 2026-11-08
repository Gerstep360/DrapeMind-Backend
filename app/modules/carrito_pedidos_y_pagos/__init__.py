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

from app.segundo_parcial.cu22_carrito_checkout.cu22_carrito import router as cu09_router
from app.segundo_parcial.cu22_carrito_checkout.cu22_checkout import router as cu10_router
from app.segundo_parcial.cu23_pagos.cu23_pagos import router as cu11_router
from app.segundo_parcial.cu24_pedidos.cu24_historial import router as cu12_router
from app.segundo_parcial.compartido.caja_online import router as cu37_router
from app.segundo_parcial.cu24_pedidos.cu24_entregas import router as cu39_router

cart_router = cu09_router

orders_router = cu12_router
orders_router.include_router(cu10_router)

payments_router = cu11_router

admin_orders_router = APIRouter()
admin_orders_router.include_router(cu37_router)
admin_orders_router.include_router(cu39_router)

__all__ = ["cart_router", "orders_router", "payments_router", "admin_orders_router"]
