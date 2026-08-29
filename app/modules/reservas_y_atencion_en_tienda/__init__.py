"""Paquete 04: Reservas y atención en tienda (PK-04).
Casos de uso:
- CU-13: Reservar varias prendas en una sucursal
- CU-14: Consultar, mostrar QR y cancelar reserva
- CU-15: Recibir y preparar reserva en sucursal
- CU-16: Atender llegada del cliente y convertir reserva en venta
- CU-38: Gestionar reservas de la sucursal
"""
from fastapi import APIRouter

from app.modules.reservas_y_atencion_en_tienda.cu13_reservar_varias_prendas_en_una_sucursal import (
    reserve,
)
from app.modules.reservas_y_atencion_en_tienda.cu14_consultar_mostrar_qr_y_cancelar_reserva import (
    router as cu14_router,
)
from app.modules.reservas_y_atencion_en_tienda.cu15_recibir_y_preparar_reserva_en_sucursal import (
    router as cu15_router,
)
from app.modules.reservas_y_atencion_en_tienda.cu16_atender_llegada_del_cliente_y_convertir_reserva_en_venta import (
    router as cu16_router,
)
from app.modules.reservas_y_atencion_en_tienda.cu38_gestionar_reservas_de_la_sucursal import (
    router as cu38_router,
)
from app.schemas.api import ReservationOut

reservations_router = cu14_router
reservations_router.add_api_route(
    "",
    reserve,
    methods=["POST"],
    response_model=ReservationOut,
    status_code=201,
    summary="CU-13: Reservar carrito o prendas en sucursal",
    description="CU-13. Reserva varias variantes en una sucursal. Si items se omite, usa el carrito actual.",
)
reservations_router.include_router(cu15_router)
reservations_router.include_router(cu16_router)

admin_reservations_router = cu38_router


__all__ = ["reservations_router", "admin_reservations_router"]


