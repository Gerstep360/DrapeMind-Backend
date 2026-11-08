from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.models import User
from app.segundo_parcial.compartido.reportes import (
    admin,
    BusinessReport,
    pdf_response,
    document,
    require_active_subscription,
)

router = APIRouter(tags=["CU-26 · Exportar reportes"])


@router.get("/business-reports/{report_id}/pdf")
def report_pdf(
    report_id: int, user: User = Depends(admin), db: Session = Depends(get_db)
):
    require_active_subscription(db, user.tenant_id, "ai_reports")
    row = db.get(BusinessReport, report_id)
    if not row:
        raise HTTPException(404, "Reporte no encontrado")
    report = row.resultado
    data = report["datos"]
    lines = [
        data["empresa"],
        f"Periodo: {data['desde']} a {data['hasta']} | {data['sucursal']}",
        f"Consulta: {row.consulta}",
        "",
        f"Pedidos pagados: {data['pedidos_pagados']}",
        f"Ingreso neto cobrado: Bs {data['ingreso_neto_cobrado']}",
        f"Unidades disponibles ahora: {data['inventario_actual']['unidades_disponibles']}",
        "",
        data["alcance"],
        "",
        report["analisis"],
        "",
        "Recomendaciones:",
        *report["recomendaciones"],
    ]
    return pdf_response(document(report["titulo"], lines), f"reporte-{row.id}.pdf")
