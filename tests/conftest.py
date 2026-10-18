"""Legacy business tests use plain Session; SaaS tests exercise the real scoped session/middleware."""
import pytest
from sqlalchemy import event
from sqlalchemy.orm import Session
from app.core.tenancy import tenant_scope
from app.db.tenant_session import TenantSession
from app.models.saas import TenantOwned


@event.listens_for(Session,'before_flush')
def legacy_test_owner(db,*args):
    if isinstance(db,TenantSession): return
    for obj in db.new:
        if isinstance(obj,TenantOwned) and obj.tenant_id is None: obj.tenant_id=1


@pytest.fixture(autouse=True)
def legacy_company_scope(request,monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings,'SECRET_KEY','test-only-signing-key-not-used-by-the-running-application')
    with tenant_scope(1):
        if not request.node.fspath.basename.startswith('test_saas'):
            # Existing endpoint unit tests override get_db, not SessionLocal. Their
            # purpose is business behavior; the SaaS HTTP suite tests the real resolver.
            from app.core import saas_middleware
            monkeypatch.setattr(saas_middleware,'resolve_scope',lambda headers,path:1)
        yield
