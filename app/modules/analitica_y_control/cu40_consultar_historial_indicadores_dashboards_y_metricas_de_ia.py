"""CU-40: Consultar historial, indicadores, dashboards y métricas de IA.
Paquete: Analítica y control (PK-08).
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from decimal import Decimal
from pydantic import BaseModel
from app.api.deps import require_role
from app.db.session import get_db
from app.models import AIInteraction, AISession, Order, Payment, Product, Role, User
from app.services.financials import net_payments

router = APIRouter()


class DashboardOut(BaseModel):
    total_ventas: Decimal | float
    total_pedidos: int
    total_usuarios: int
    total_productos: int
    pedidos_por_estado: dict[str, int]



@router.get(
    "/dashboard",
    response_model=DashboardOut,
    summary="CU-40: Dashboard integral de ventas y stock",
    description="Calcula ingresos totales, órdenes completadas, stock crítico y métricas generales del negocio.",
)
def obtener_dashboard_comercial(
    _staff: User = Depends(require_role(Role.ADMIN, Role.VENDEDOR)),
    db: Session = Depends(get_db),
) -> dict:
    """CU-40: Métricas comerciales e indicadores clave (KPIs)."""
    total_ventas = net_payments(db)
    total_pedidos = db.scalar(select(func.count(Order.id))) or 0
    total_usuarios = db.scalar(select(func.count(User.id))) or 0
    total_productos = db.scalar(select(func.count(Product.id)).where(Product.activo == True)) or 0

    pedidos_por_estado = dict(
        db.execute(select(Order.estado, func.count(Order.id)).group_by(Order.estado)).all()
    )

    return {
        "total_ventas": total_ventas,
        "total_pedidos": total_pedidos,
        "total_usuarios": total_usuarios,
        "total_productos": total_productos,
        "pedidos_por_estado": pedidos_por_estado,
    }


@router.get(
    "/ai/analytics",
    summary="CU-40: Auditoría y métricas de rendimiento de IA (NVIDIA / Altair)",
    description="Muestra el tiempo promedio de inferencia, herramientas más utilizadas y desglose de interacciones.",
)
def obtener_metricas_ia(
    limit: int = Query(default=30, ge=1, le=100),
    _staff: User = Depends(require_role(Role.ADMIN)),
    db: Session = Depends(get_db),
) -> dict:
    """CU-40: Métricas de auditoría y rendimiento del asistente de IA."""
    total_sessions = db.scalar(select(func.count(AISession.id))) or 0
    total_interactions = db.scalar(select(func.count(AIInteraction.id))) or 0
    avg_duration = db.scalar(select(func.avg(AIInteraction.duracion_ms))) or 0.0

    recent_interactions = db.scalars(
        select(AIInteraction).order_by(AIInteraction.id.desc()).limit(limit)
    ).all()

    return {
        "total_sesiones_ia": total_sessions,
        "total_interacciones": total_interactions,
        "latencia_promedio_ms": round(float(avg_duration), 2),
        "interacciones_recientes": [
            {
                "id": i.id,
                "sesion_id": i.sesion_id,
                "tipo": i.tipo,
                "tool": i.tool_principal,
                "duracion_ms": i.duracion_ms,
                "estado": i.estado,
                "timestamp": i.created_at.isoformat() if i.created_at else None,
            }
            for i in recent_interactions
        ],
    }


@router.get("/sales/history", summary="CU-40: Historial de ventas")
def sales_history(
    limit: int = Query(default=100, ge=1, le=500),
    admin: User = Depends(require_role(Role.ADMIN)),
    db: Session = Depends(get_db),
) -> list[dict]:
    from app.api.v1.endpoints.admin import sales_history as scoped_history
    return scoped_history(limit=limit,admin=admin,db=db)


@router.get("/metrics/sales-inventory", summary="CU-40: Métricas de ventas e inventario")
def sales_inventory_metrics(
    admin: User = Depends(require_role(Role.ADMIN)),
    db: Session = Depends(get_db),
) -> dict:
    from app.api.v1.endpoints.admin import sales_inventory_metrics as scoped_metrics
    return scoped_metrics(admin=admin,db=db)


@router.get("/metrics/ai", summary="CU-40: Métricas de uso de IA")
def ai_metrics(
    admin: User = Depends(require_role(Role.ADMIN)),
    db: Session = Depends(get_db),
) -> list[dict]:
    from app.api.v1.endpoints.admin import ai_metrics as scoped_ai
    return scoped_ai(admin=admin,db=db)
