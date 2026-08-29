"""Paquete 06: Realidad aumentada (PK-06).
Casos de uso:
- CU-17: Utilizar vestidor virtual mediante realidad aumentada
"""
from fastapi import APIRouter

from app.modules.realidad_aumentada.cu17_utilizar_vestidor_virtual_mediante_realidad_aumentada import router as cu17_router

ar_router = cu17_router

__all__ = ["ar_router"]

