"""Read-only local acceptance checks against the configured PostgreSQL database."""
import json
from sqlalchemy import text, select
from fastapi.testclient import TestClient
from app.core.config import BACKEND_DIR
from app.db.session import engine, SessionLocal
from app.core.tenancy import tenant_scope
from app.models import Product
from app.main import app


def main():
    with engine.connect() as connection:
        role=connection.execute(text('SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user')).one()
        assert not any(role), 'El proceso HTTP no debe ser superusuario ni omitir RLS'
        assert connection.scalar(text('SELECT count(*) FROM productos')) == 0, 'Sin contexto no debe haber datos'
        assert connection.scalar(text("SELECT count(*) FROM pg_class WHERE relname='productos' AND relrowsecurity AND relforcerowsecurity")) == 1
    credentials=json.loads((BACKEND_DIR/'.saas-demo-credentials.json').read_text(encoding='utf-8'))
    client=TestClient(app)
    states=[]
    for account in credentials['companies']:
        public={'X-Tenant':account['company']}
        result=client.post('/api/v1/auth/login',headers=public,json={'email':account['email'],'password':account['password']})
        assert result.status_code==200, ('login',result.status_code)
        headers={**public,'Authorization':'Bearer '+result.json()['access_token']}
        me=client.get('/api/v1/auth/me',headers=headers);assert me.status_code==200
        tenant_id=me.json()['tenant_id']
        with tenant_scope(tenant_id),SessionLocal() as db:
            products=list(db.scalars(select(Product)))
            assert products and all(p.tenant_id==tenant_id for p in products)
            product_id=products[0].id
        state=client.get('/api/v1/saas/me',headers=headers)
        assert state.status_code==200 and state.json()['tenant']['slug']==account['company']
        catalog=client.get('/api/v1/catalog/products',headers=headers)
        assert catalog.status_code==200
        states.append((headers,tenant_id,product_id))
    a,b=states[:2]
    assert client.get(f'/api/v1/catalog/products/{b[2]}',headers=a[0]).status_code==404
    assert client.get(f'/api/v1/catalog/products/{a[2]}',headers=b[0]).status_code==404
    assert client.get('/api/v1/catalog/products',headers={**a[0],'X-Tenant':b[0]['X-Tenant']}).status_code==403
    with engine.connect() as connection:
        connection.execute(text("SELECT set_config('app.tenant_id',:tenant,true)"),{'tenant':str(a[1])})
        assert connection.scalar(text('SELECT count(*) FROM productos WHERE tenant_id=:other'),{'other':b[1]})==0
        assert connection.execute(text('UPDATE productos SET nombre=nombre WHERE id=:other'),{'other':b[2]}).rowcount==0
        connection.rollback()
    print('PostgreSQL: RLS obligatorio, rol sin bypass, login empresarial y aislamiento cruzado verificados para dos empresas.')

if __name__=='__main__': main()
