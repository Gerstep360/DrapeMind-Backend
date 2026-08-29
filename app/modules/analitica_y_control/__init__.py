"""Paquete 08: Analítica y control (PK-08).
Casos de uso:
- CU-40: Consultar historial, indicadores, dashboards y métricas de IA
"""
from fastapi import APIRouter

from app.modules.analitica_y_control.cu40_consultar_historial_indicadores_dashboards_y_metricas_de_ia import router as cu40_router

analytics_router = cu40_router

__all__ = ["analytics_router"]

