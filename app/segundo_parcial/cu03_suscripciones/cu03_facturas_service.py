"""Read-only Stripe reconciliation; amounts come from invoices, never plan estimates."""
from datetime import datetime, timezone
from urllib.parse import urlparse, urlencode
from fastapi import HTTPException
from sqlalchemy import select
from app.models.saas import Tenant, SaaSPrice, SaaSPlan
from app.segundo_parcial.cu03_suscripciones.cu03_facturas_modelo import SaaSInvoice
from app.services.stripe_payments import _stripe_request


def identifier(value):
    return value.get('id') if isinstance(value,dict) else value


def stripe_link(value):
    if not isinstance(value,str): return None
    url=urlparse(value)
    return value if url.scheme=='https' and (url.hostname=='stripe.com' or (url.hostname or '').endswith('.stripe.com')) else None


def store_invoice(db, invoice, tenant=None):
    invoice_id=invoice.get('id','')
    subscription=identifier(invoice.get('subscription') or (invoice.get('parent') or {}).get('subscription_details',{}).get('subscription'))
    customer=identifier(invoice.get('customer'))
    if not isinstance(invoice_id,str) or not invoice_id.startswith('in_') or not subscription or invoice.get('currency') not in ('bob','usd'):
        return None
    tenant=tenant or db.scalar(select(Tenant).where(Tenant.stripe_customer_id==customer))
    if not tenant or tenant.stripe_customer_id!=customer: return None
    metadata=(invoice.get('parent') or {}).get('subscription_details',{}).get('metadata') or {}
    if metadata.get('tenant_id') not in (None,str(tenant.id)):
        raise HTTPException(409,'La factura no corresponde a la empresa registrada')
    status=invoice.get('status')
    if status not in ('draft','open','paid','void','uncollectible') or not invoice.get('created'): return None
    row=db.get(SaaSInvoice,invoice_id)
    if row and row.tenant_id!=tenant.id: raise HTTPException(409,'La factura ya pertenece a otra empresa')
    if not row:
        row=SaaSInvoice(id=invoice_id,tenant_id=tenant.id)
        db.add(row)
    row.subscription_id=subscription
    row.number=invoice.get('number')
    row.status=status;row.currency=invoice['currency'].upper()
    row.amount_due_minor=max(0,int(invoice.get('amount_due') or 0))
    row.amount_paid_minor=max(0,int(invoice.get('amount_paid') or 0))
    row.amount_remaining_minor=max(0,int(invoice.get('amount_remaining') or 0))
    row.attempt_count=int(invoice.get('attempt_count') or 0)
    row.livemode=bool(invoice.get('livemode'))
    row.hosted_url=stripe_link(invoice.get('hosted_invoice_url'))
    row.pdf_url=stripe_link(invoice.get('invoice_pdf'))
    row.issued_at=datetime.fromtimestamp(invoice['created'],timezone.utc)
    paid=(invoice.get('status_transitions') or {}).get('paid_at')
    row.paid_at=datetime.fromtimestamp(paid,timezone.utc) if paid else None
    row.synced_at=datetime.now(timezone.utc)
    for line in invoice.get('lines',{}).get('data',[]):
        price=identifier(line.get('price') or (line.get('pricing') or {}).get('price_details',{}).get('price'))
        record=db.get(SaaSPrice,price) if price else None
        plan=db.get(SaaSPlan,record.plan_id) if record else None
        if plan:
            row.plan_name=plan.name
            break
    return row


def sync_invoice_page(db, cursor=None):
    from app.services.saas_billing import stripe_ready
    stripe_ready()
    params={'limit':100}
    if cursor: params['starting_after']=cursor
    page=_stripe_request('GET','invoices?'+urlencode(params))
    rows=page.get('data')
    if not isinstance(rows,list): raise HTTPException(502,'Stripe no devolvió un historial válido')
    imported=0
    for invoice in rows:
        if store_invoice(db,invoice): imported+=1
    next_cursor=rows[-1]['id'] if rows and page.get('has_more') else None
    if page.get('has_more') and (not next_cursor or next_cursor==cursor):
        raise HTTPException(502,'No se pudo continuar el historial de Stripe. Reintenta la actualización.')
    db.commit()
    return {'imported':imported,'reviewed':len(rows),'next_cursor':next_cursor}
