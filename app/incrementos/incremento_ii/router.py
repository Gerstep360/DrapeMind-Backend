from fastapi import APIRouter
from .cu11_proveedores import router as supply_router
from .cu12_cu14_offline import router as offline_router

router = APIRouter()
router.include_router(supply_router)
router.include_router(offline_router)
