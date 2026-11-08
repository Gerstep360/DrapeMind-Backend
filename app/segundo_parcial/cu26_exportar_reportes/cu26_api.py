from fastapi import APIRouter
from app.segundo_parcial.compartido.indicadores import (
    BusinessReport,
    Decimal,
    Depends,
    HTTPException,
    Response,
    Session,
    User,
    admin,
    get_db,
    require_active_subscription,
    workbook,
)

router = APIRouter(prefix="", tags=["CU-26 · exportar_reportes"])


@router.get("/business-reports/{report_id}/xlsx")
def export_report(
    report_id: int, user: User = Depends(admin), db: Session = Depends(get_db)
):
    require_active_subscription(db, user.tenant_id, "ai_reports")
    row = db.get(BusinessReport, report_id)
    if not row:
        raise HTTPException(404, "Reporte no encontrado")
    report = row.resultado
    data = report["datos"]
    rows = [
        ["Reporte empresarial", report["titulo"]],
        ["Empresa", data["empresa"]],
        ["Sucursal", data["sucursal"]],
        ["Desde", data["desde"]],
        ["Hasta", data["hasta"]],
        ["Consulta", row.consulta],
        ["Pedidos pagados", data["pedidos_pagados"]],
        ["Ingreso neto cobrado (BOB)", float(Decimal(data["ingreso_neto_cobrado"]))],
        [
            "Unidades disponibles ahora",
            data["inventario_actual"]["unidades_disponibles"],
        ],
        ["Alcance", data["alcance"]],
        ["Análisis NVIDIA", report["analisis"]],
        ["Prenda", "Unidades"],
    ]
    rows.extend([item["nombre"], item["cantidad"]] for item in data["prendas_vendidas"])
    rows.extend(["Recomendación", action] for action in report["recomendaciones"])
    return Response(
        workbook(rows),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f'attachment; filename="reporte-{row.id}.xlsx"',
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )
