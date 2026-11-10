from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.models import User
from app.segundo_parcial.compartido.reportes import (
    admin,
    BusinessReport,
    pdf_response,
    require_active_subscription,
)
from .cu26_documento import report_document

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
    return pdf_response(report_document(report,row.consulta,row.id), f"reporte-{row.id}.pdf")
