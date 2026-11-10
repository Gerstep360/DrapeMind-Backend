"""Platform-only subscription revenue and invoice history."""
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from io import BytesIO
from typing import Literal
from xml.sax.saxutils import escape
from fastapi import APIRouter, Depends, Query, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import select, or_
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.models import User
from app.models.saas import Tenant
from app.core.config import settings
from app.segundo_parcial.compartido.saas import platform_admin
from app.segundo_parcial.cu03_suscripciones.cu03_facturas_modelo import SaaSInvoice
from app.segundo_parcial.cu03_suscripciones.cu03_facturas_service import sync_invoice_page

router=APIRouter(prefix='/saas/billing',tags=['CU-03 · Reportes y pagos SaaS'])


class SyncRequest(BaseModel):
    cursor: str | None=Field(default=None,max_length=120,pattern=r'^in_[A-Za-z0-9_]+$')


def filtered_query(tenant_id=None, since=None, until=None, status=None, mode='all', search=''):
    if since and until and since>until: raise HTTPException(422,'La fecha inicial debe ser anterior a la fecha final')
    query=select(SaaSInvoice,Tenant,User).join(Tenant,Tenant.id==SaaSInvoice.tenant_id).outerjoin(User,User.id==Tenant.admin_user_id)
    if tenant_id: query=query.where(SaaSInvoice.tenant_id==tenant_id)
    if since: query=query.where(SaaSInvoice.issued_at>=datetime.combine(since,time.min,tzinfo=timezone.utc))
    if until: query=query.where(SaaSInvoice.issued_at<datetime.combine(until+timedelta(days=1),time.min,tzinfo=timezone.utc))
    if status: query=query.where(SaaSInvoice.status==status)
    if mode!='all': query=query.where(SaaSInvoice.livemode.is_(mode=='live'))
    if search:
        text='%'+search.strip()+'%'
        query=query.where(or_(Tenant.name.ilike(text),User.nombre.ilike(text),User.email.ilike(text),SaaSInvoice.number.ilike(text)))
    return query.order_by(SaaSInvoice.issued_at.desc(),SaaSInvoice.id.desc())


def serialize(row,tenant,admin):
    return {'id':row.id,'tenant_id':tenant.id,'company':tenant.name,'admin':admin.nombre if admin else None,
        'email':admin.email if admin else tenant.contact_email,'number':row.number,'plan':row.plan_name,
        'status':row.status,'currency':row.currency,'amount_due':Decimal(row.amount_due_minor)/100,
        'amount_paid':Decimal(row.amount_paid_minor)/100,'amount_remaining':Decimal(row.amount_remaining_minor)/100,
        'attempts':row.attempt_count,'livemode':row.livemode,'issued_at':row.issued_at,'paid_at':row.paid_at,
        'invoice_url':row.hosted_url,'pdf_url':row.pdf_url}


@router.get('')
def billing_report(response: Response,tenant_id: int | None=Query(None,gt=0), since: date | None=None, until: date | None=None,
        status: Literal['draft','open','paid','void','uncollectible'] | None=None,
        mode: Literal['all','test','live']='all', search: str=Query('',max_length=100),
        offset: int=Query(0,ge=0),limit: int=Query(25,ge=1,le=100),
        admin: User=Depends(platform_admin),db: Session=Depends(get_db)):
    response.headers['Cache-Control']='private, no-store'
    rows=db.execute(filtered_query(tenant_id,since,until,status,mode,search)).all()
    groups={};monthly={}
    for row,tenant,_ in rows:
        key=(row.currency,row.livemode)
        group=groups.setdefault(key,{'currency':row.currency,'livemode':row.livemode,'paid_amount_minor':0,'pending_amount_minor':0,'paid_count':0,'pending_count':0})
        if row.status=='paid':
            group['paid_amount_minor']+=row.amount_paid_minor;group['paid_count']+=1
            month=row.issued_at.strftime('%Y-%m')
            bucket=monthly.setdefault((month,*key),{'month':month,'currency':row.currency,'livemode':row.livemode,'amount_minor':0})
            bucket['amount_minor']+=row.amount_paid_minor
        elif row.status=='open':
            group['pending_amount_minor']+=row.amount_remaining_minor;group['pending_count']+=1
    last=db.scalar(select(SaaSInvoice.synced_at).order_by(SaaSInvoice.synced_at.desc()).limit(1))
    return {'items':[serialize(*row) for row in rows[offset:offset+limit]],'total':len(rows),
        'summary':list(groups.values()),'monthly':sorted(monthly.values(),key=lambda r:(r['month'],r['currency'],r['livemode'])),
        'companies':len({r[0].tenant_id for r in rows}),'last_synced_at':last,
        'stripe_configured':settings.STRIPE_SECRET_KEY.startswith(('sk_','rk_')),
        'stripe_mode':'live' if settings.STRIPE_SECRET_KEY.startswith(('sk_live_','rk_live_')) else 'test'}


@router.post('/sync')
def sync_history(payload: SyncRequest,admin: User=Depends(platform_admin),db: Session=Depends(get_db)):
    return sync_invoice_page(db,payload.cursor)


@router.get('/export')
def export_history(format: Literal['pdf','xlsx']='xlsx',tenant_id: int | None=Query(None,gt=0),since: date | None=None,until: date | None=None,
        status: Literal['draft','open','paid','void','uncollectible'] | None=None,mode: Literal['all','test','live']='all',search: str=Query('',max_length=100),
        admin: User=Depends(platform_admin),db: Session=Depends(get_db)):
    records=db.execute(filtered_query(tenant_id,since,until,status,mode,search).limit(10001)).all()
    if len(records)>10000: raise HTTPException(422,'Acota las fechas para exportar hasta 10.000 facturas por archivo.')
    labels={'paid':'Pagada','open':'Pendiente','draft':'Borrador','void':'Anulada','uncollectible':'Incobrable'}
    header=['Empresa','Administrador','Correo','Factura','Plan','Emisión','Estado','Moneda','Importe abonado','Por cobrar','Modo']
    rows=[]
    for invoice,tenant,user in records:
        rows.append([tenant.name,user.nombre if user else '',user.email if user else '',invoice.number or invoice.id,invoice.plan_name or 'Plan anterior',invoice.issued_at.strftime('%d/%m/%Y'),labels[invoice.status],invoice.currency,float(Decimal(invoice.amount_paid_minor)/100),float(Decimal(invoice.amount_remaining_minor)/100),'Real' if invoice.livemode else 'Prueba'])
    if format=='xlsx':
        from app.segundo_parcial.compartido.indicadores import workbook
        content=workbook([['DrapeMind · Pagos de suscripciones'],['Facturas emitidas',str(since or 'Desde el inicio'),str(until or 'Hasta hoy')],['Importes abonados según Stripe. Pruebas y monedas se identifican por separado.'],header,*rows])
        media='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    else:
        from reportlab.platypus import SimpleDocTemplate,Paragraph,Spacer,LongTable,TableStyle
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4,landscape
        stream=BytesIO();styles=getSampleStyleSheet();doc=SimpleDocTemplate(stream,pagesize=landscape(A4),rightMargin=28,leftMargin=28,topMargin=30,bottomMargin=30)
        body=[Paragraph('DRAPEMIND / SUSCRIPCIONES',styles['Title']),Paragraph('Historial de facturas y pagos empresariales',styles['Heading2']),Paragraph(escape(f'Facturas emitidas: {since or "Desde el inicio"} — {until or "Hasta hoy"}. Importes abonados según Stripe; monedas y modos se presentan por separado.'),styles['Normal']),Spacer(1,16)]
        table_rows=[[Paragraph(escape(str(v)),styles['BodyText']) for v in ['Empresa / administrador','Factura / plan','Emisión / estado','Abonado','Por cobrar','Modo']]]
        for row in rows:
            values=[f'{row[0]} / {row[1]}',f'{row[3]} / {row[4]}',f'{row[5]} / {row[6]}',f'{row[7]} {row[8]:.2f}',f'{row[7]} {row[9]:.2f}',row[10]]
            table_rows.append([Paragraph(escape(v),styles['BodyText']) for v in values])
        table=LongTable(table_rows,colWidths=[190,190,125,95,95,70],repeatRows=1)
        table.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#DFFF36')),('VALIGN',(0,0),(-1,-1),'TOP'),('BOTTOMPADDING',(0,0),(-1,-1),9),('TOPPADDING',(0,0),(-1,-1),9),('ROWBACKGROUNDS',(0,1),(-1,-1),[colors.HexColor('#F7F5EF'),colors.white]),('LINEBELOW',(0,0),(-1,0),1,colors.black)]))
        body.append(table)
        def footer(canvas,document):
            canvas.setFont('Helvetica',8);canvas.drawString(28,16,f'DrapeMind · Historial SaaS · Página {document.page}')
        doc.build(body,onFirstPage=footer,onLaterPages=footer);content=stream.getvalue();media='application/pdf'
    return Response(content,media_type=media,headers={'Content-Disposition':f'attachment; filename="pagos-saas.{format}"','Cache-Control':'private, no-store','X-Content-Type-Options':'nosniff'})
