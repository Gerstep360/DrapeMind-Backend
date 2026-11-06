"""Business capabilities registered once for native inference and MCP."""

from pydantic import BaseModel, Field


class IndicatorArgs(BaseModel):
    days: int = Field(default=30, ge=1, le=366)
    sucursal_id: int | None = Field(default=None, gt=0)


class BranchArgs(BaseModel):
    sucursal_id: int | None = Field(default=None, gt=0)


class HistoryArgs(BaseModel):
    limit: int = Field(default=10, ge=1, le=50)


def indicators(context, args):
    from app.incrementos.incremento_iv.router import dashboard

    return dashboard(args.days, args.sucursal_id, context.user, context.db)


def predictions(context, args):
    from app.incrementos.incremento_iv.router import predictions as read

    return read(args.sucursal_id, context.user, context.db)


def saved_reports(context, args):
    from app.incrementos.incremento_iii.router import report_history

    rows = report_history(args.limit, context.user, context.db)
    return [
        {
            "id": row["id"],
            "titulo": row["titulo"],
            "consulta": row["consulta"],
            "datos": row["datos"],
            "extracto_analisis": row["analisis"][:1000],
        }
        for row in rows
    ]


def suppliers(context, args):
    from app.incrementos.incremento_ii.cu11_proveedores import suppliers as read
    from app.incrementos.incremento_ii.schemas import SupplierOut

    return [
        SupplierOut.model_validate(row).model_dump(mode="json")
        for row in read(context.user, context.db)[: args.limit]
    ]


def supply_orders(context, args):
    from app.incrementos.incremento_ii.cu11_proveedores import orders

    return orders(context.user, context.db)[: args.limit]


def register(registry, definition):
    for name, description, model, handler in [
        (
            "get_business_indicators",
            "Indicadores comerciales reales por periodo y sucursal: cobros netos, pedidos pagados, prendas e inventario actual.",
            IndicatorArgs,
            indicators,
        ),
        (
            "get_demand_predictions",
            "Demanda estimada y patrones calculados con pedidos reales. Informa historial insuficiente; no inventa predicciones.",
            BranchArgs,
            predictions,
        ),
        (
            "get_saved_business_reports",
            "Consulta reportes generativos guardados de esta empresa. Requiere plan con reportes IA; no genera otra inferencia.",
            HistoryArgs,
            saved_reports,
        ),
        (
            "get_suppliers",
            "Consulta proveedores registrados en la empresa actual.",
            HistoryArgs,
            suppliers,
        ),
        (
            "get_supply_orders",
            "Consulta pedidos de abastecimiento y sus estados en esta empresa.",
            HistoryArgs,
            supply_orders,
        ),
    ]:
        registry[name] = definition(
            name, description, model, handler, allowed_roles=("ADMIN",)
        )
