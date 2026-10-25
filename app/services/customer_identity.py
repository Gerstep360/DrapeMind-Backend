"""One personal login, explicit store membership, no shared staff privileges."""
import json
from fastapi import HTTPException
from sqlalchemy import select, inspect
from app.core.tenancy import system_scope
from app.db.tenant_session import bind_tenant
from app.models import User, Role, UserStatus, UserStyleProfile, Address
from app.models.saas import CustomerAccount, Tenant
from app.core.security import verify_password

def personal_snapshot(value):
    return {c.name:getattr(value,c.name) for c in inspect(type(value)).columns if c.name not in ('id','tenant_id','usuario_id','created_at','updated_at','primer_outfit_ia','adn_estilo_ia')}


def remember_personal_data(db,user):
    if not user.customer_account_id:
        return
    account=db.get(CustomerAccount,user.customer_account_id)
    db.flush()
    account.name,account.phone=user.nombre,user.telefono
    profile=db.scalar(select(UserStyleProfile).where(UserStyleProfile.usuario_id==user.id))
    data={'style':personal_snapshot(profile) if profile else None,'addresses':[personal_snapshot(a) for a in db.scalars(select(Address).where(Address.usuario_id==user.id))]}
    account.personal_data=json.loads(json.dumps(data,default=str))


def attach_legacy_customer(db,user,password):
    """Link only after the existing customer's password has been verified."""
    if user.rol!=Role.CLIENTE or user.customer_account_id:
        return
    account=db.scalar(select(CustomerAccount).where(CustomerAccount.email==user.email).with_for_update())
    if account and (not account.active or not verify_password(password,account.password_hash)):
        return  # Never merge different credentials just because email matches.
    if not account:
        account=CustomerAccount(email=user.email,password_hash=user.password_hash,name=user.nombre,phone=user.telefono)
        db.add(account);db.flush()
    user.customer_account_id=account.id
    db.flush()
    remember_personal_data(db,user)
    db.commit()


def enter_customer_store(db,account,slug,password=None):
    if not account.active:
        raise HTTPException(403,'Tu cuenta está inactiva. Contacta con soporte.')
    # All cross-store operations are limited to this validated identity's own
    # membership. The returned HTTP token has a single tenant as before.
    with system_scope(db):
        tenant=db.scalar(select(Tenant).where(Tenant.slug==slug,Tenant.active.is_(True)))
        if not tenant:
            raise HTTPException(404,'Esta tienda no está disponible')
        db.scalar(select(CustomerAccount.id).where(CustomerAccount.id==account.id).with_for_update())
        member=db.scalar(select(User).where(User.tenant_id==tenant.id,User.customer_account_id==account.id))
        if not member:
            conflict=db.scalar(select(User).where(User.tenant_id==tenant.id,User.email==account.email))
            if conflict and password and conflict.rol==Role.CLIENTE and not conflict.is_platform_admin and conflict.customer_account_id is None and verify_password(password,conflict.password_hash):
                conflict.customer_account_id=account.id
                member=conflict
            elif conflict:
                raise HTTPException(409,'Este correo tiene un acceso independiente en esta tienda. Contacta con su administración para vincularlo de forma segura.')
            else:
                member=User(tenant_id=tenant.id,customer_account_id=account.id,is_platform_admin=False,nombre=account.name,email=account.email,password_hash=account.password_hash,telefono=account.phone,rol=Role.CLIENTE,estado=UserStatus.ACTIVO)
                db.add(member)
            db.flush()
        if member.estado!=UserStatus.ACTIVO or member.rol!=Role.CLIENTE or member.is_platform_admin:
            raise HTTPException(403,'Tu acceso a esta tienda no está disponible')
        member_id=member.id
    bind_tenant(db,tenant.id)
    member=db.get(User,member_id)
    member.nombre,member.telefono=account.name,account.phone
    data=account.personal_data or {}
    if data:
        profile=db.scalar(select(UserStyleProfile).where(UserStyleProfile.usuario_id==member.id))
        if data.get('style'):
            if not profile:
                profile=UserStyleProfile(usuario_id=member.id);db.add(profile)
            for key,value in data['style'].items(): setattr(profile,key,value)
        addresses=list(db.scalars(select(Address).where(Address.usuario_id==member.id)))
        for values in data.get('addresses',[]):
            match=next((address for address in addresses if all(getattr(address,key)==values.get(key) for key in ('alias','ciudad','direccion'))),None)
            if match:
                for key,value in values.items():setattr(match,key,value)
                addresses.remove(match)
            else:db.add(Address(usuario_id=member.id,**values))
        for address in addresses:db.delete(address)
    db.commit()
    return member,tenant
