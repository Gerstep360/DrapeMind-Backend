from fastapi import APIRouter

from app.api.v1.endpoints import admin, ai, ar, auth, cart, catalog, orders, payments, reservations, users, ws

api_router = APIRouter()
api_router.include_router(auth.router, prefix="/auth", tags=["Autenticacion"])
api_router.include_router(users.router, prefix="/users", tags=["Usuarios y direcciones"])
api_router.include_router(catalog.router, prefix="/catalog", tags=["Catalogo y favoritos"])
api_router.include_router(cart.router, prefix="/cart", tags=["Carrito"])
api_router.include_router(reservations.router, prefix="/reservations", tags=["Reservas"])
api_router.include_router(orders.router, prefix="/orders", tags=["Pedidos"])
api_router.include_router(payments.router, prefix="/payments", tags=["Pagos"])
api_router.include_router(ai.router, prefix="/ai", tags=["IA - Gemma"])
api_router.include_router(ar.router, prefix="/ar", tags=["Realidad aumentada"])
api_router.include_router(admin.router, prefix="/admin", tags=["Administracion"])
api_router.include_router(ws.router, prefix="/ws")
