"""Entrada SaaS del Incremento I; los servicios de dominio siguen compartidos."""
from fastapi import APIRouter
from app.api.v1.endpoints.saas import router as saas_router

router = APIRouter()
router.include_router(saas_router, prefix='/saas', tags=['Empresas, planes y suscripciones SaaS'])
