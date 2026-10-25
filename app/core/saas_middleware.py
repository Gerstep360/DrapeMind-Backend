from fastapi import HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
from sqlalchemy import select
from app.core.tenancy import tenant_scope, system_scope
from app.core.security import decode_access_token


def resolve_scope(headers, path):
    from app.db.session import SessionLocal
    from app.models import User, UserStatus
    from app.models.saas import Tenant
    from app.services.saas import require_active_subscription
    if path == '/api/v1/auth/login' or path.startswith('/api/v1/saas/companies'):
        # La identidad de login se determina en el servidor antes de vincular tenant.
        # Un token anterior o un contexto guardado no decide qué cuenta autenticar.
        return None
    # Provider endpoints authenticate the raw body signature, then resolve the
    # company from the persisted payment/customer. They do not accept client scope.
    if path in ('/api/v1/payments/webhook','/api/v1/payments/stripe-webhook','/api/v1/payments/stripe-local-webhook','/api/v1/saas/stripe-webhook'):
        return None
    token = headers.get('authorization', '')
    slug = headers.get('x-tenant', '').strip().lower()
    tenant_id, platform = None, False
    with SessionLocal() as db:
        if token.startswith('Bearer '):
            try: claims = decode_access_token(token[7:])
            except ValueError: raise HTTPException(401, 'Sesión inválida o expirada')
            platform = claims.get('platform') is True
            tenant_id = claims.get('tid')
            if not platform and (not isinstance(tenant_id,int) or tenant_id <= 0):
                raise HTTPException(401, 'Inicia sesión nuevamente en tu empresa')
            with system_scope(db):
                user = db.get(User, int(claims['sub']))
                if not user or user.estado != UserStatus.ACTIVO or user.tenant_id != tenant_id or bool(user.is_platform_admin) != platform:
                    raise HTTPException(401, 'Sesión sin una empresa autorizada')
            if platform:
                if not path.startswith('/api/v1/saas') and path not in ('/api/v1/auth/me','/api/v1/auth/refresh'):
                    raise HTTPException(403, 'Accede al panel de administración SaaS')
                return None
        if tenant_id:
            tenant = db.get(Tenant, tenant_id)
            if not tenant or (slug and slug != tenant.slug):
                raise HTTPException(403, 'La empresa seleccionada no corresponde a la sesión')
        elif slug:
            tenant = db.scalar(select(Tenant).where(Tenant.slug == slug))
            if not tenant: raise HTTPException(404, 'Empresa no encontrada')
            tenant_id = tenant.id
        if path.startswith('/api/v1/saas') or path.endswith('/stripe-webhook'):
            return tenant_id
        if not tenant_id:
            raise HTTPException(400, 'Selecciona una empresa para continuar')
        if not path.startswith('/api/v1/auth'):
            feature = None
            if '/reports/' in path and path.startswith('/api/v1/ai'): feature = 'ai_reports'
            elif '/metrics/' in path or '/sales/history' in path: feature = 'reports'
            elif '/reservations' in path: feature = 'reservations'
            elif any(part in path for part in ('/catalog','/orders','/cart','/payments','/inventory','/products','/sales')): feature = 'products_sales'
            require_active_subscription(db, tenant_id, feature)
        return tenant_id


class SaaSMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        if request.method == 'OPTIONS' or not request.url.path.startswith('/api/v1/') or request.url.path.endswith('/openapi.json'):
            return await call_next(request)
        try:
            tenant_id = await run_in_threadpool(resolve_scope, request.headers, request.url.path)
            with tenant_scope(tenant_id):
                return await call_next(request)
        except HTTPException as exc:
            return JSONResponse(status_code=exc.status_code, content={'detail':exc.detail})
