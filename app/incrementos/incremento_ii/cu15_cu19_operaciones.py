"""Incremento II: registro durable, conciliación, conflictos y atención de reservas."""
from datetime import datetime,timezone
from uuid import UUID
from fastapi import APIRouter,Depends,HTTPException,Response,Query
from fastapi.encoders import jsonable_encoder
from sqlalchemy import select,or_
from sqlalchemy.orm import Session
from app.api.deps import require_roles
from app.db.session import get_db
from app.models import User,UserStatus,Role,Branch,BranchStaff,Reservation,ReservationItem,ProductVariant,Product
from app.services.saas import require_active_subscription,aware
from app.services.store import expire_due_reservations
from .models import SyncOperation,SyncAudit
from .schemas import (Input,SyncEnvelope,OfflineReservation,CashSale,ReservationPickup,
    ConflictResolution,ReservationPreparation,OperationLookup)
from .common import digest
from .retail_service import branch_access,apply_cash_sale,fail
from .cu12_cu14_offline import apply_reservation

router=APIRouter(tags=['Incremento II · CU-15 a CU-19'])
authorized=require_roles(Role.ADMIN,Role.ENCARGADO,Role.CAJERO,Role.CLIENTE,Role.VENDEDOR)
staff=require_roles(Role.ADMIN,Role.ENCARGADO,Role.CAJERO)
manager=require_roles(Role.ADMIN,Role.ENCARGADO)
CASH_ROLES=(Role.ADMIN,Role.ENCARGADO,Role.CAJERO)


def operation_payload(op):
    return {'id':op.id,'operacion_id':op.operacion_id,'tipo':op.tipo,'usuario_id':op.usuario_id,
        'sucursal_id':op.sucursal_id,'estado':op.estado,'payload':op.payload,'resultado':op.resultado,
        'error':op.error,'intentos':op.intentos,'created_at':op.created_at,'updated_at':op.updated_at}


def role_for_kind(user,kind):
    if kind!='RESERVATION' and user.rol not in CASH_ROLES:
        fail('ROLE_FORBIDDEN','Solo el personal de caja autorizado puede registrar una venta',403)


def branch_ids(db,user):
    return select(BranchStaff.sucursal_id).where(BranchStaff.usuario_id==user.id,BranchStaff.activo.is_(True))


def attempt(db,op,owner,actor,*,accept_saved_price=False,reason=None):
    op.intentos+=1
    op.updated_at=datetime.now(timezone.utc)
    try:
        with db.begin_nested():
            if owner.estado!=UserStatus.ACTIVO:
                fail('USER_INACTIVE','El usuario que creó la operación ya no está autorizado',403)
            role_for_kind(owner,op.tipo)
            require_active_subscription(db,owner.tenant_id,'offline')
            require_active_subscription(db,owner.tenant_id,'reservations' if op.tipo=='RESERVATION' else 'products_sales')
            branch_access(db,owner,op.sucursal_id)
            if op.tipo=='RESERVATION':
                result=apply_reservation(OfflineReservation.model_validate(op.payload),Response(),owner,db,commit_changes=False)
            else:
                model=ReservationPickup if op.tipo=='PICKUP' else CashSale
                result={'sale':apply_cash_sale(db,owner,model.model_validate(op.payload),
                    pickup=op.tipo=='PICKUP',accept_saved_price=accept_saved_price)}
            op.resultado=jsonable_encoder(result);op.error=None;op.estado='CONFIRMED'
    except HTTPException as error:
        detail=error.detail if isinstance(error.detail,dict) else {'code':'OPERATION_CONFLICT','message':error.detail}
        op.estado='CONFLICT';op.error=jsonable_encoder(detail);op.resultado=None
    db.add(SyncAudit(operacion_id=op.id,actor_id=actor.id,accion='MANAGER_RETRY' if reason else 'SYNC',
        detalle={'estado':op.estado,'error':op.error,'motivo':reason,'aceptar_precio_guardado':accept_saved_price}))
    db.flush()
    return op


@router.post('/offline/operations')
def synchronize(payload:SyncEnvelope,user:User=Depends(authorized),db:Session=Depends(get_db)):
    role_for_kind(user,payload.tipo)
    require_active_subscription(db,user.tenant_id,'offline')
    if not db.get(Branch,payload.payload['sucursal_id']):
        fail('BRANCH_UNAVAILABLE','La sucursal no pertenece a esta empresa',404)
    expire_due_reservations(db)
    db.scalar(select(User).where(User.id==user.id).with_for_update())
    operation_id=payload.payload['operacion_id']
    fingerprint=digest(payload.model_dump(mode='json'))
    op=db.scalar(select(SyncOperation).where(SyncOperation.usuario_id==user.id,SyncOperation.operacion_id==operation_id).with_for_update())
    if op:
        if op.payload_hash!=fingerprint:
            fail('OPERATION_REUSED','Esta operación ya fue recibida con otros datos')
        if op.estado in ('CONFIRMED','REJECTED'):
            return operation_payload(op)
    else:
        op=SyncOperation(usuario_id=user.id,sucursal_id=payload.payload['sucursal_id'],operacion_id=operation_id,
            tipo=payload.tipo,payload=payload.payload,payload_hash=fingerprint)
        db.add(op);db.flush()
    attempt(db,op,user,user)
    db.commit()
    return operation_payload(op)


@router.get('/offline/operations')
def my_operations(before_id:int|None=None,limit:int=Query(200,ge=1,le=200),user:User=Depends(authorized),db:Session=Depends(get_db)):
    stmt=select(SyncOperation).where(SyncOperation.usuario_id==user.id)
    if before_id:stmt=stmt.where(SyncOperation.id<before_id)
    return [operation_payload(o) for o in db.scalars(stmt.order_by(SyncOperation.id.desc()).limit(limit))]


@router.post('/offline/operations/results')
def operation_results(payload:OperationLookup,user:User=Depends(authorized),db:Session=Depends(get_db)):
    return [operation_payload(o) for o in db.scalars(select(SyncOperation).where(
        SyncOperation.usuario_id==user.id,SyncOperation.operacion_id.in_([str(i) for i in payload.operaciones])))]


@router.post('/offline/operations/{operation_uuid}/cancel')
def cancel_pending(operation_uuid:UUID,user:User=Depends(authorized),db:Session=Depends(get_db)):
    db.scalar(select(User).where(User.id==user.id).with_for_update())
    op=db.scalar(select(SyncOperation).where(SyncOperation.usuario_id==user.id,SyncOperation.operacion_id==str(operation_uuid)).with_for_update())
    if not op:fail('NOT_FOUND','La operación no se recibió en el servidor',404)
    if op.tipo!='RESERVATION' or op.estado not in ('CONFLICT','REJECTED'):
        fail('ALREADY_PROCESSED','Esta operación no se puede cancelar. Comprueba su resultado.')
    if op.estado!='REJECTED':
        op.estado='REJECTED';op.updated_at=datetime.now(timezone.utc)
        op.error={'code':'OWNER_CANCELLED','message':'La solicitud fue cancelada por su titular.'}
        db.add(SyncAudit(operacion_id=op.id,actor_id=user.id,accion='OWNER_CANCEL',detalle={'estado':'REJECTED'}))
        db.commit()
    return operation_payload(op)


@router.get('/retail/conflicts')
def conflicts(before_id:int|None=None,user:User=Depends(manager),db:Session=Depends(get_db)):
    stmt=select(SyncOperation).where(SyncOperation.estado.in_(['CONFLICT','REJECTED']))
    if user.rol!=Role.ADMIN:stmt=stmt.where(SyncOperation.sucursal_id.in_(branch_ids(db,user)))
    if before_id:stmt=stmt.where(SyncOperation.id<before_id)
    rows=list(db.scalars(stmt.order_by(SyncOperation.id.desc()).limit(200)))
    users=dict(db.execute(select(User.id,User.nombre).where(User.id.in_([o.usuario_id for o in rows]))).all())
    branches=dict(db.execute(select(Branch.id,Branch.nombre).where(Branch.id.in_([o.sucursal_id for o in rows]))).all())
    ids={i['variante_id'] for o in rows for i in o.payload['items']}
    variants={v.id:(v,p) for v,p in db.execute(select(ProductVariant,Product).join(Product,Product.id==ProductVariant.producto_id).where(ProductVariant.id.in_(ids)))}
    result=[]
    for op in rows:
        lines=[]
        for item in op.payload['items']:
            v,p=variants.get(item['variante_id'],(None,None))
            lines.append({**item,'nombre':f'{p.nombre} · {v.talla} · {v.color}' if p else 'Prenda no disponible',
                          'precio_actual':str(p.precio) if p else None})
        result.append({**operation_payload(op),'usuario_nombre':users.get(op.usuario_id,'Usuario de la tienda'),
            'sucursal_nombre':branches.get(op.sucursal_id,'Sucursal de la tienda'),'detalle_prendas':lines})
    return result


@router.get('/retail/operations/{operation_id}/audit')
def audit(operation_id:int,user:User=Depends(manager),db:Session=Depends(get_db)):
    op=db.get(SyncOperation,operation_id)
    if not op:fail('NOT_FOUND','Operación no encontrada',404)
    branch_access(db,user,op.sucursal_id,require_active=False)
    return [{'id':a.id,'actor_id':a.actor_id,'accion':a.accion,'detalle':a.detalle,'created_at':a.created_at}
            for a in db.scalars(select(SyncAudit).where(SyncAudit.operacion_id==operation_id).order_by(SyncAudit.id))]


@router.post('/retail/operations/{operation_id}/resolve')
def resolve(operation_id:int,payload:ConflictResolution,user:User=Depends(manager),db:Session=Depends(get_db)):
    op=db.get(SyncOperation,operation_id)
    if not op:fail('NOT_FOUND','Operación no encontrada',404)
    branch_access(db,user,op.sucursal_id,require_active=False)
    owner=db.scalar(select(User).where(User.id==op.usuario_id).with_for_update())
    op=db.scalar(select(SyncOperation).where(SyncOperation.id==operation_id).with_for_update().execution_options(populate_existing=True))
    if op.estado!='CONFLICT':
        fail('ALREADY_RESOLVED','La operación ya fue resuelta. Actualiza la lista.')
    if payload.accion=='REJECT':
        if op.tipo!='RESERVATION' and not payload.efectivo_devuelto:
            fail('REFUND_REQUIRED','Confirma la devolución del efectivo antes de anular esta venta',422)
        op.estado='REJECTED';op.updated_at=datetime.now(timezone.utc)
        op.error={'code':'MANAGER_REJECTED','message':payload.motivo}
        db.add(SyncAudit(operacion_id=op.id,actor_id=user.id,accion='REJECT',
            detalle={'motivo':payload.motivo,'efectivo_devuelto':payload.efectivo_devuelto}))
    else:
        attempt(db,op,owner,user,accept_saved_price=payload.aceptar_precio_guardado,reason=payload.motivo)
    db.commit()
    return operation_payload(op)


def reservation_snapshot(db,reservation):
    return {'id':reservation.id,'codigo_publico':str(reservation.codigo_publico),'sucursal_id':reservation.sucursal_id,
        'estado':reservation.estado,'vence_at':aware(reservation.vence_at).isoformat(),
        'usuario_id':reservation.usuario_id,'items':[{'variante_id':i.variante_id,'cantidad':i.cantidad,
            'precio_unitario':str(i.precio_referencia)} for i in db.scalars(
                select(ReservationItem).where(ReservationItem.reserva_id==reservation.id))]}


def attending_snapshots(db,user):
    stmt=select(Reservation).where(Reservation.estado.in_(['PENDIENTE','CONFIRMADA','EN_PREPARACION','LISTA','RETIRADA']))
    if user.rol!=Role.ADMIN:stmt=stmt.where(Reservation.sucursal_id.in_(branch_ids(db,user)))
    return [reservation_snapshot(db,r) for r in db.scalars(stmt.order_by(Reservation.id.desc()).limit(200))]


@router.get('/retail/reservations')
def attending(user:User=Depends(staff),db:Session=Depends(get_db)):
    expire_due_reservations(db)
    return attending_snapshots(db,user)


@router.post('/retail/reservations/{reservation_id}/prepare')
def prepare(reservation_id:int,payload:ReservationPreparation,user:User=Depends(staff),db:Session=Depends(get_db)):
    expire_due_reservations(db)
    r=db.scalar(select(Reservation).where(Reservation.id==reservation_id).with_for_update())
    if not r:fail('NOT_FOUND','Reserva no encontrada',404)
    branch_access(db,user,r.sucursal_id)
    allowed={'PENDIENTE':('CONFIRMADA','EN_PREPARACION','LISTA'),'CONFIRMADA':('EN_PREPARACION','LISTA'),
             'EN_PREPARACION':('LISTA',),'LISTA':()}
    if r.estado!=payload.estado and payload.estado not in allowed.get(r.estado,()):
        fail('INVALID_STATE','La reserva no permite ese cambio de estado')
    r.estado=payload.estado;r.preparado_por_id=user.id;r.preparado_at=datetime.now(timezone.utc)
    db.commit()
    return reservation_snapshot(db,r)
