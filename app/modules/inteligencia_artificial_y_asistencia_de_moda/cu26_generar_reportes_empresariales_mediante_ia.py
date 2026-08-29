"""CU-26: Generar reportes empresariales mediante IA.
Paquete: Inteligencia artificial y asistencia de moda (PK-05).
"""
from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import require_role
from app.db.session import get_db
from app.models import Order, Product, Role, User
from app.services.ai import call_gemma

router = APIRouter()


@router.post(
    "/reports/executive-summary",
    summary="CU-26: Generar resumen ejecutivo inteligente de ventas y tendencias",
    description="Analiza métricas de pedidos, prendas populares y genera un resumen gerencial en lenguaje natural.",
)
async def generar_resumen_ejecutivo_ia(
    _admin: User = Depends(require_role(Role.ADMIN)),
    db: Session = Depends(get_db),
) -> dict:
    """CU-26: Síntesis gerencial y recomendaciones estratégicas por IA."""
    total_orders = db.scalar(select(func.count(Order.id))) or 0
    total_revenue = db.scalar(select(func.sum(Order.total))) or 0
    top_products = db.scalars(select(Product.nombre).where(Product.activo == True).limit(5)).all()

    data_summary = f"Total Pedidos: {total_orders}, Ingresos Totales: Bs {total_revenue:.2f}, Top Prendas: {', '.join(top_products)}"
    prompt = f"Analiza los siguientes indicadores del negocio de moda y redacta un informe ejecutivo con 3 oportunidades de crecimiento: {data_summary}"

    summary, _ = await call_gemma("Eres un consultor de negocios y analista estratégico de retail de lujo.", prompt)

    return {
        "indicadores_base": {
            "total_pedidos": total_orders,
            "ingresos_totales_bob": float(total_revenue),
            "prendas_analizadas": len(top_products),
        },
        "informe_ejecutivo": summary.strip(),
    }
