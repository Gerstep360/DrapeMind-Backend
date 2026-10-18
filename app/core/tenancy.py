"""Request-scoped company context. No implicit default tenant or client-selected private scope."""
from contextlib import contextmanager
from contextvars import ContextVar

tenant_context: ContextVar[int | None] = ContextVar('tenant_id', default=None)


@contextmanager
def tenant_scope(tenant_id):
    token = tenant_context.set(tenant_id)
    try:
        yield
    finally:
        tenant_context.reset(token)


@contextmanager
def system_scope(db):
    """Server-internal control-plane scope; never exposed as a query/header parameter."""
    previous = db.info.get('saas_system', False)
    db.info['saas_system'] = True
    from app.db.tenant_session import apply_database_scope
    apply_database_scope(db)
    try:
        yield db
    finally:
        db.info['saas_system'] = previous
        apply_database_scope(db)
