"""Resolver identidad y destino después de validar credenciales, sin roles elegidos por el cliente."""
from fastapi import HTTPException
from sqlalchemy import and_, func, or_, select
from app.core.security import create_access_token, verify_password
from app.core.tenancy import system_scope
from app.db.tenant_session import bind_tenant
from app.models import User, UserStatus, UserStyleProfile, Role
from app.models.saas import Tenant
from app.schemas.api import UserOut
from app.services.saas import subscription_state


def credentials_error():
    return HTTPException(401,'Correo o contraseña incorrectos',headers={'WWW-Authenticate':'Bearer'})


def user_profile(db,user,tenant=None):
    tenant = tenant or (db.get(Tenant,user.tenant_id) if user.tenant_id else None)
    user.has_style_profile = False if user.is_platform_admin else db.scalar(
        select(UserStyleProfile.id).where(UserStyleProfile.usuario_id==user.id)
    ) is not None
    return UserOut.model_validate(user).model_copy(update={
        'tenant_slug':tenant.slug if tenant else None,
        'tenant_name':tenant.name if tenant else None,
    })


def sign_in(db,email,password,tenant_slug=None):
    query=select(User,Tenant).outerjoin(Tenant,User.tenant_id==Tenant.id).where(func.lower(User.email)==email.strip().lower())
    if tenant_slug:
        # El enlace de tienda puede resolver correos repetidos; nunca concede permisos.
        query=query.where(or_(Tenant.slug==tenant_slug,and_(User.is_platform_admin.is_(True),User.tenant_id.is_(None))))
    with system_scope(db):
        candidates=list(db.execute(query.limit(21)).all())
        if not candidates or len(candidates)>20:
            raise credentials_error()
        verified=[(user,tenant) for user,tenant in candidates if verify_password(password,user.password_hash)]
    if not verified:
        raise credentials_error()
    if len(verified)>1:
        raise HTTPException(409,{'code':'STORE_LINK_REQUIRED','message':'Este acceso existe en varias tiendas. Abre el enlace de la tienda donde quieres entrar.'})
    user,tenant=verified[0]
    if user.estado!=UserStatus.ACTIVO:
        raise HTTPException(403,'Tu cuenta está inactiva. Contacta con tu tienda.')
    platform=bool(user.is_platform_admin and user.tenant_id is None)
    if not platform and (not tenant or not tenant.active or user.is_platform_admin):
        raise HTTPException(403,'El acceso de esta tienda no está disponible. Contacta con su administración.')
    bind_tenant(db,None if platform else tenant.id)
    profile=user_profile(db,user,tenant)
    if platform:
        destination='/saas-platform'
    elif not subscription_state(db,tenant.id)[3]:
        destination='/subscription'
    elif user.rol==Role.CLIENTE:
        destination='/catalog' if profile.has_style_profile else '/onboarding'
    elif user.rol==Role.CAJERO:
        destination='/pos'
    else:
        destination='/dashboard'
    token,expires=create_access_token(user.id,user.rol.value,tenant_id=user.tenant_id,platform=platform)
    return dict(access_token=token,token_type='bearer',expires_in=expires,user=profile,
                tenant=None if platform else dict(id=tenant.id,slug=tenant.slug,name=tenant.name),redirect_path=destination)
