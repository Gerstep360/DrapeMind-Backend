"""CU-22/23: durable, idempotent card-on-file purchases queued by offline clients."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.api.deps import require_roles
from app.db.session import get_db
from app.models import User, Role, UserStatus, Order, Payment, Branch, Address, Cart, CartItem
from app.core.config import settings
from app.services.saas import require_active_subscription, aware
from app.services.store import cart_payload, checkout_cart, cancel_unpaid_order, confirm_payment
from app.services.stripe_payments import _stripe_request, create_intent, minor_units
from app.incrementos.incremento_ii.common import digest
from .deferred_models import SavedCard, DeferredPurchase, PURCHASE_TERMINAL

router = APIRouter(prefix='/payments', tags=['Compras pendientes y tarjetas guardadas'])
customer = require_roles(Role.CLIENTE)
TERMINAL = PURCHASE_TERMINAL
CONSENT = 'deferred-v1'


class Input(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)


class SetupInput(Input):
    operacion_id: UUID
    aceptar_guardado_y_cobros_diferidos: bool


class SetupResult(Input):
    setup_intent_id: str = Field(pattern=r'^seti_[A-Za-z0-9_]+$', max_length=100)
    aceptar_guardado_y_cobros_diferidos: bool


class Item(Input):
    variante_id: int = Field(gt=0)
    cantidad: int = Field(gt=0, le=100)


class PurchaseInput(Input):
    operacion_id: UUID
    items: list[Item] = Field(min_length=1,max_length=50)
    tipo_entrega: str = Field(pattern=r'^(RECOJO|DELIVERY)$')
    sucursal_id: int | None = Field(None,gt=0)
    direccion_id: int | None = Field(None,gt=0)
    codigo_promocion: str | None = Field(None,max_length=60)
    tarjeta_id: int | None = Field(None,gt=0)
    total_autorizado: Decimal = Field(gt=0,max_digits=10,decimal_places=2)
    autorizar_cobro_automatico: bool = False
    creado_en_dispositivo: datetime

    @model_validator(mode='after')
    def valid_purchase(self):
        if len({item.variante_id for item in self.items}) != len(self.items):
            raise ValueError('Incluye cada variante una sola vez')
        if self.tipo_entrega=='RECOJO' and not self.sucursal_id:
            raise ValueError('Selecciona una sucursal para el recojo')
        if self.tipo_entrega=='DELIVERY' and not self.direccion_id:
            raise ValueError('Selecciona una dirección de entrega')
        if self.creado_en_dispositivo.tzinfo is None:
            raise ValueError('La fecha de la compra debe incluir zona horaria')
        if self.tarjeta_id and not self.autorizar_cobro_automatico:
            raise ValueError('Autoriza expresamente el importe y el cobro al recuperar conexión')
        return self


class MethodInput(Input):
    tarjeta_id: int = Field(gt=0)
    autorizar_cobro_automatico: bool


def stripe_ready():
    if settings.PAYMENT_PROVIDER != 'stripe' or not settings.STRIPE_SECRET_KEY.startswith(('sk_','rk_')):
        raise HTTPException(503,'Esta función requiere Stripe configurado. No se simulan cobros.')


def card_out(row):
    return {key:getattr(row,key) for key in ('id','marca','ultimos_cuatro','mes_vencimiento','anio_vencimiento')}


def own_card(db,user,card_id):
    row=db.scalar(select(SavedCard).where(SavedCard.id==card_id,SavedCard.usuario_id==user.id,SavedCard.activo.is_(True)))
    if not row:raise HTTPException(404,'Tarjeta no encontrada en tu cuenta y tienda')
    now=datetime.now(timezone.utc)
    if (row.anio_vencimiento,row.mes_vencimiento)<(now.year,now.month):
        raise HTTPException(409,'La tarjeta guardada venció. Registra otra con conexión.')
    return row


def owned(db,user,operation):
    row=db.scalar(select(DeferredPurchase).where(DeferredPurchase.operacion_id==str(operation),DeferredPurchase.usuario_id==user.id).execution_options(populate_existing=True))
    if not row:raise HTTPException(404,'Compra pendiente no encontrada en esta cuenta y tienda')
    return row


def purchase_out(row):
    return {'operacion_id':row.operacion_id,'estado':row.estado,'pedido_id':row.pedido_id,
        'total_autorizado':str(row.total_autorizado),'mensaje':row.mensaje,'vence_at':row.vence_at,
        'tarjeta_id':row.tarjeta_id,'created_at':row.created_at,'updated_at':row.updated_at}


@router.post('/cards/setup')
def setup(payload:SetupInput,response:Response,user:User=Depends(customer),db:Session=Depends(get_db)):
    stripe_ready();response.headers['Cache-Control']='no-store'
    if not payload.aceptar_guardado_y_cobros_diferidos:raise HTTPException(422,'Acepta el guardado y los futuros cobros autorizados antes de continuar')
    user=db.scalar(select(User).where(User.id==user.id).with_for_update())
    if not user.stripe_customer_id:
        record=_stripe_request('POST','customers',key=f'card-customer-{user.tenant_id}-{user.id}',data={
            'email':user.email,'name':user.nombre,'metadata[tenant_id]':str(user.tenant_id),'metadata[user_id]':str(user.id)})
        user.stripe_customer_id=record['id'];db.commit()
    result=_stripe_request('POST','setup_intents',key=f'card-setup-{user.tenant_id}-{user.id}-{payload.operacion_id}',data={
        'customer':user.stripe_customer_id,'usage':'off_session','payment_method_types[]':'card',
        'metadata[tenant_id]':str(user.tenant_id),'metadata[user_id]':str(user.id),'metadata[consent]':CONSENT})
    return {'setup_intent_id':result['id'],'client_secret':result['client_secret'],'publishable_key':settings.STRIPE_PUBLISHABLE_KEY}


@router.post('/cards/confirm',status_code=201)
def save_card(payload:SetupResult,user:User=Depends(customer),db:Session=Depends(get_db)):
    stripe_ready()
    db.scalar(select(User).where(User.id==user.id).with_for_update())
    if not payload.aceptar_guardado_y_cobros_diferidos:raise HTTPException(422,'Falta autorización para guardar la tarjeta')
    intent=_stripe_request('GET','setup_intents/'+payload.setup_intent_id)
    metadata=intent.get('metadata') or {}
    if not user.stripe_customer_id or intent.get('customer')!=user.stripe_customer_id or metadata.get('tenant_id')!=str(user.tenant_id) or metadata.get('user_id')!=str(user.id) or metadata.get('consent')!=CONSENT:
        raise HTTPException(404,'El registro de tarjeta no corresponde a tu cuenta y tienda')
    if intent.get('status')!='succeeded' or intent.get('usage')!='off_session':raise HTTPException(409,'Stripe todavía no confirmó el guardado de la tarjeta')
    method=_stripe_request('GET','payment_methods/'+str(intent.get('payment_method','')))
    if method.get('customer')!=user.stripe_customer_id or method.get('type')!='card':raise HTTPException(409,'La tarjeta no está vinculada a tu identidad de pago')
    row=db.scalar(select(SavedCard).where(SavedCard.usuario_id==user.id,SavedCard.stripe_payment_method==method['id']))
    if not row:row=SavedCard(usuario_id=user.id,stripe_payment_method=method['id']);db.add(row)
    card=method['card'];row.setup_intent=intent['id'];row.marca=card['brand'];row.ultimos_cuatro=card['last4']
    row.mes_vencimiento=card['exp_month'];row.anio_vencimiento=card['exp_year'];row.activo=True;row.consentimiento_version=CONSENT
    db.commit();return card_out(row)


@router.get('/cards')
def cards(user:User=Depends(customer),db:Session=Depends(get_db)):
    return [card_out(row) for row in db.scalars(select(SavedCard).where(SavedCard.usuario_id==user.id,SavedCard.activo.is_(True)).order_by(SavedCard.id))]


@router.delete('/cards/{card_id}')
def remove_card(card_id:int,user:User=Depends(customer),db:Session=Depends(get_db)):
    row=own_card(db,user,card_id)
    if db.scalar(select(DeferredPurchase.id).where(DeferredPurchase.usuario_id==user.id,DeferredPurchase.tarjeta_id==row.id,DeferredPurchase.estado.not_in(TERMINAL))):
        raise HTTPException(409,'Primero cancela o termina las compras pendientes que usan esta tarjeta')
    row.activo=False;db.commit();return {'message':'Tarjeta retirada de esta tienda'}


@router.get('/deferred/context')
def context(user:User=Depends(customer),db:Session=Depends(get_db)):
    require_active_subscription(db,user.tenant_id,'offline')
    now=datetime.now(timezone.utc)
    return {'owner':f'{user.tenant_id}:{user.id}','downloaded_at':now,'valid_until':now+timedelta(days=7),
        'cart':cart_payload(db,user.id),'cards':cards(user,db),'delivery_fee':str(settings.DELIVERY_FEE_BOB),
        'branches':[{'id':b.id,'nombre':b.nombre,'direccion':b.direccion} for b in db.scalars(select(Branch).where(Branch.activo.is_(True)))],
        'addresses':[{'id':a.id,'alias':a.alias,'ciudad':a.ciudad} for a in db.scalars(select(Address).where(Address.usuario_id==user.id))]}


def finish(db,row,state,message):
    row.estado=state;row.mensaje=message;row.updated_at=datetime.now(timezone.utc)
    row.siguiente_intento=None if state in TERMINAL else row.updated_at+timedelta(seconds=45)
    db.commit();return row


def cancel_resources(db,row,state,message):
    if row.pedido_id:
        order=db.scalar(select(Order).where(Order.id==row.pedido_id).execution_options(populate_existing=True))
        if order and order.paid_at:return finish(db,row,'PAGADA','El pago ya fue confirmado; la compra no se canceló.')
        # Caller first obtains a terminal canceled PaymentIntent from Stripe.
        if order and order.estado=='PENDIENTE_PAGO':cancel_unpaid_order(db,order,row.usuario_id,provider_checked=True)
    return finish(db,row,state,message)


def clear_matching_cart(db,row):
    cart=db.scalar(select(Cart).where(Cart.usuario_id==row.usuario_id,Cart.estado=='ACTIVO').with_for_update())
    if cart:
        items=list(db.scalars(select(CartItem).where(CartItem.carrito_id==cart.id)))
        current=sorted((x.variante_id,x.cantidad) for x in items)
        saved=sorted((x['variante_id'],x['cantidad']) for x in row.payload['items'])
        if current==saved:cart.estado='CONVERTIDO';db.commit()


def process(db,row,*,allow_charge=True,cancel=False):
    if row.estado in TERMINAL:return row
    user=db.get(User,row.usuario_id)
    now=datetime.now(timezone.utc);expired=aware(row.vence_at)<=now
    payment=db.scalar(select(Payment).where(Payment.pedido_id==row.pedido_id,Payment.proveedor=='STRIPE')) if row.pedido_id else None
    if payment and payment.estado=='APROBADO':
        clear_matching_cart(db,row);return finish(db,row,'PAGADA','Stripe confirmó el pago. Tu pedido está registrado.')
    if not row.pedido_id:
        db.scalar(select(User).where(User.id==user.id).with_for_update())
        row=db.scalar(select(DeferredPurchase).where(DeferredPurchase.id==row.id).execution_options(populate_existing=True))
        if row.estado in TERMINAL:return row
        if cancel or expired:return finish(db,row,'CANCELADA' if cancel else 'VENCIDA','Compra anulada sin cobro ni descuento de stock.')
        if not row.tarjeta_id or not row.consentimiento_at:return finish(db,row,'REQUIERE_METODO','Añade una tarjeta con conexión y autoriza el importe para continuar.')
        if not allow_charge:return row
        try:
            require_active_subscription(db,user.tenant_id,'offline');require_active_subscription(db,user.tenant_id,'products_sales')
            if user.estado!=UserStatus.ACTIVO or user.rol!=Role.CLIENTE:raise HTTPException(403,'La cuenta ya no está autorizada para comprar')
            if 'offline.use' not in user.permisos:raise HTTPException(403,'Tu cuenta no tiene habilitadas las compras diferidas')
            stripe_ready();own_card(db,user,row.tarjeta_id)
            if user.customer_account_id:
                from app.models.saas import CustomerAccount
                account=db.get(CustomerAccount,user.customer_account_id)
                if not account or not account.active:raise HTTPException(403,'La cuenta personal no está disponible')
            order=checkout_cart(db,user,row.payload['tipo_entrega'],row.payload.get('direccion_id'),Decimal('0'),
                'Compra guardada sin conexión',row.payload.get('codigo_promocion'),row.payload.get('sucursal_id'),
                'WEB',row.operacion_id,row.payload_hash,[(i['variante_id'],i['cantidad']) for i in row.payload['items']],row.total_autorizado,deferred_purchase=row)
            db.refresh(row)
            if row.estado in TERMINAL:return row
        except HTTPException as exc:
            db.rollback();row=db.get(DeferredPurchase,row.id)
            return finish(db,row,'RECHAZADA',str(exc.detail)[:500])
    try:
        stripe_ready()
        if payment is None or not payment.referencia_externa:
            if not allow_charge and not cancel and not expired:return row
            # Creating an unconfirmed intent cannot charge. Persist its reference before confirmation.
            result=create_intent(db,row.pedido_id,row.usuario_id)
            payment=db.get(Payment,result['payment_id'])
        # Same lock order as signed Stripe webhooks. Keep it through confirmation/cancel.
        payment=db.scalar(select(Payment).where(Payment.id==payment.id).with_for_update().execution_options(populate_existing=True))
        order=db.scalar(select(Order).where(Order.id==row.pedido_id).with_for_update().execution_options(populate_existing=True))
        if payment.estado=='APROBADO' or order.paid_at:
            clear_matching_cart(db,row);return finish(db,row,'PAGADA','Stripe confirmó el pago. Tu pedido está registrado.')
        if order.estado=='CANCELADO':cancel=True
        intent=_stripe_request('GET','payment_intents/'+payment.referencia_externa)
        metadata=intent.get('metadata') or {}
        if intent.get('amount')!=minor_units(row.total_autorizado) or intent.get('currency')!='bob' or metadata.get('tenant_id')!=str(row.tenant_id) or metadata.get('order_id')!=str(row.pedido_id) or metadata.get('payment_id')!=str(payment.id):
            return finish(db,row,'PENDIENTE_RESULTADO','El pago requiere conciliación: sus datos no coinciden. No se intentó otro cobro.')
        if intent.get('status')=='succeeded':
            if intent.get('amount_received')!=minor_units(row.total_autorizado):return finish(db,row,'PENDIENTE_RESULTADO','Stripe debe confirmar el importe íntegro.')
            confirm_payment(db,payment.referencia_externa,'APROBADO');clear_matching_cart(db,row)
            return finish(db,row,'PAGADA','Stripe confirmó el pago. Tu pedido está registrado.')
        if intent.get('status')=='canceled':
            confirm_payment(db,payment.referencia_externa,'RECHAZADO')
            return cancel_resources(db,row,'CANCELADA' if cancel else 'VENCIDA' if expired else 'RECHAZADA','Compra cancelada sin cobro; las prendas se liberaron.')
        if cancel or expired:
            result=_stripe_request('POST','payment_intents/'+payment.referencia_externa+'/cancel',key=f'deferred-cancel-{row.id}')
            if result.get('status')!='canceled':return finish(db,row,'PENDIENTE_RESULTADO','La cancelación debe confirmarse con Stripe antes de liberar las prendas.')
            confirm_payment(db,payment.referencia_externa,'RECHAZADO')
            return cancel_resources(db,row,'CANCELADA' if cancel else 'VENCIDA','Compra cancelada sin cobro; las prendas se liberaron.')
        status=intent.get('status');error=(intent.get('last_payment_error') or {}).get('code')
        if status=='processing':return finish(db,row,'PROCESANDO_PAGO','Stripe está procesando el pago. No repitas la compra.')
        if status=='requires_action' or error=='authentication_required':return finish(db,row,'REQUIERE_AUTENTICACION','Tu banco solicita verificación. Continúa con conexión para autorizar el pago.')
        if status=='requires_payment_method' and error:
            result=_stripe_request('POST','payment_intents/'+payment.referencia_externa+'/cancel',key=f'deferred-decline-{row.id}')
            if result.get('status')=='canceled':
                confirm_payment(db,payment.referencia_externa,'RECHAZADO')
                return cancel_resources(db,row,'RECHAZADA','Stripe rechazó el pago. La compra se anuló y las prendas se liberaron.')
        if not allow_charge:return finish(db,row,'PENDIENTE_RESULTADO','Se verificará el resultado con Stripe sin repetir el cobro.')
        require_active_subscription(db,user.tenant_id,'offline')
        card=own_card(db,user,row.tarjeta_id)
        if user.estado!=UserStatus.ACTIVO or user.rol!=Role.CLIENTE or 'offline.use' not in user.permisos:raise HTTPException(403,'La cuenta no tiene autorización para continuar')
        if user.customer_account_id:
            from app.models.saas import CustomerAccount
            account=db.get(CustomerAccount,user.customer_account_id)
            if not account or not account.active:raise HTTPException(403,'La cuenta personal no está disponible')
        if not intent.get('customer'):
            _stripe_request('POST','payment_intents/'+payment.referencia_externa,data={'customer':user.stripe_customer_id},key=f'deferred-customer-{row.id}')
        elif intent['customer']!=user.stripe_customer_id:raise HTTPException(409,'El titular de pago requiere conciliación')
        row.intentos+=1;row.estado='PROCESANDO_PAGO';row.siguiente_intento=now+timedelta(seconds=45);db.flush()
        try:
            _stripe_request('POST','payment_intents/'+payment.referencia_externa+'/confirm',data={
                'payment_method':card.stripe_payment_method,'off_session':'true'},key=f'deferred-confirm-{row.id}')
        except HTTPException:
            pass  # Reconcile the known intent; a timeout or HTTP 402 is never proof of no charge.
        return process(db,row,allow_charge=False)
    except HTTPException as exc:
        db.rollback();row=db.get(DeferredPurchase,row.id)
        if not cancel and row.pedido_id and exc.status_code in (402,403,404,409):
            return process(db,row,allow_charge=False,cancel=True)
        return finish(db,row,'PENDIENTE_RESULTADO','No pudimos confirmar el resultado con Stripe. La compra sigue guardada y se verificará sin duplicar el cobro.')


@router.post('/deferred',status_code=201)
def submit(payload:PurchaseInput,user:User=Depends(customer),db:Session=Depends(get_db)):
    require_active_subscription(db,user.tenant_id,'offline')
    db.scalar(select(User).where(User.id==user.id).with_for_update())
    canonical=payload.model_dump(mode='json');signature=digest(canonical)
    row=db.scalar(select(DeferredPurchase).where(DeferredPurchase.usuario_id==user.id,DeferredPurchase.operacion_id==str(payload.operacion_id)))
    if row:
        if row.payload_hash!=signature:raise HTTPException(409,'La operación ya existe con otros datos; no se inició otra compra')
    else:
        now=datetime.now(timezone.utc)
        if payload.creado_en_dispositivo>now+timedelta(minutes=5):raise HTTPException(422,'Revisa la fecha y hora de tu dispositivo')
        if payload.tarjeta_id:own_card(db,user,payload.tarjeta_id)
        row=DeferredPurchase(usuario_id=user.id,operacion_id=str(payload.operacion_id),payload_hash=signature,payload=canonical,
            tarjeta_id=payload.tarjeta_id,total_autorizado=payload.total_autorizado,
            consentimiento_at=now if payload.autorizar_cobro_automatico else None,
            vence_at=min(payload.creado_en_dispositivo+timedelta(hours=24),now+timedelta(hours=24)))
        requested=sorted((i.variante_id,i.cantidad) for i in payload.items)
        pending=db.scalars(select(DeferredPurchase).where(DeferredPurchase.usuario_id==user.id,DeferredPurchase.estado.not_in(TERMINAL)))
        if any(sorted((i['variante_id'],i['cantidad']) for i in other.payload['items'])==requested for other in pending):
            row.estado='RECHAZADA';row.mensaje='Estas prendas ya tienen una compra pendiente. Revisa o cancela la primera; no se realizó otro cobro.'
        db.add(row);db.commit()
    db.commit()
    return purchase_out(process(db,row))


@router.get('/deferred')
def purchases(user:User=Depends(customer),db:Session=Depends(get_db)):
    return [purchase_out(row) for row in db.scalars(select(DeferredPurchase).where(DeferredPurchase.usuario_id==user.id).order_by(DeferredPurchase.id.desc()).limit(100))]


@router.post('/deferred/cancel-pending')
def cancel_pending(payload:PurchaseInput,user:User=Depends(customer),db:Session=Depends(get_db)):
    """Persist a cancellation tombstone even when the original submission response was lost."""
    db.scalar(select(User).where(User.id==user.id).with_for_update())
    row=db.scalar(select(DeferredPurchase).where(DeferredPurchase.usuario_id==user.id,DeferredPurchase.operacion_id==str(payload.operacion_id)))
    signature=digest(payload.model_dump(mode='json'))
    if not row:
        row=DeferredPurchase(usuario_id=user.id,operacion_id=str(payload.operacion_id),payload_hash=signature,
            payload=payload.model_dump(mode='json'),total_autorizado=payload.total_autorizado,
            estado='CANCELADA',mensaje='Compra cancelada antes de procesarla; no se realizó ningún cobro.',vence_at=datetime.now(timezone.utc))
        db.add(row);db.commit();return purchase_out(row)
    if row.payload_hash!=signature:raise HTTPException(409,'La cancelación no corresponde al contenido de esta operación')
    db.commit();return purchase_out(process(db,row,allow_charge=False,cancel=True))


@router.get('/deferred/{operation}')
def status(operation:UUID,user:User=Depends(customer),db:Session=Depends(get_db)):
    return purchase_out(process(db,owned(db,user,operation),allow_charge=False))


@router.post('/deferred/{operation}/sync')
def sync(operation:UUID,user:User=Depends(customer),db:Session=Depends(get_db)):
    return purchase_out(process(db,owned(db,user,operation)))


@router.post('/deferred/{operation}/cancel')
def cancel(operation:UUID,user:User=Depends(customer),db:Session=Depends(get_db)):
    return purchase_out(process(db,owned(db,user,operation),allow_charge=False,cancel=True))


@router.post('/deferred/{operation}/method')
def choose_method(operation:UUID,payload:MethodInput,user:User=Depends(customer),db:Session=Depends(get_db)):
    row=owned(db,user,operation)
    if row.estado!='REQUIERE_METODO' or row.pedido_id:raise HTTPException(409,'Esta compra ya tiene una autorización o está cerrada')
    if not payload.autorizar_cobro_automatico:raise HTTPException(422,'Autoriza expresamente el importe para continuar')
    card=own_card(db,user,payload.tarjeta_id);row.tarjeta_id=card.id;row.consentimiento_at=datetime.now(timezone.utc);db.commit()
    return purchase_out(process(db,row))


@router.post('/deferred/{operation}/authenticate')
def authenticate(operation:UUID,response:Response,user:User=Depends(customer),db:Session=Depends(get_db)):
    response.headers['Cache-Control']='no-store';row=owned(db,user,operation)
    row=process(db,row,allow_charge=False)
    if row.estado!='REQUIERE_AUTENTICACION':return {'purchase':purchase_out(row)}
    card=own_card(db,user,row.tarjeta_id)
    payment=db.scalar(select(Payment).where(Payment.pedido_id==row.pedido_id,Payment.proveedor=='STRIPE'))
    try:
        _stripe_request('POST','payment_intents/'+payment.referencia_externa+'/confirm',data={
            'payment_method':card.stripe_payment_method,'use_stripe_sdk':'true'},key=f'deferred-auth-{row.id}')
    except HTTPException:pass
    intent=_stripe_request('GET','payment_intents/'+payment.referencia_externa)
    return {'client_secret':intent.get('client_secret') if intent.get('status')=='requires_action' else None,
            'publishable_key':settings.STRIPE_PUBLISHABLE_KEY,'purchase':purchase_out(process(db,row,allow_charge=False))}
