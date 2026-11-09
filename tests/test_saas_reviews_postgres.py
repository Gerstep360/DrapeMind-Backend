"""Review and downloaded-cart contracts on migrated PostgreSQL with forced RLS."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
import pytest
from test_saas_incremento_ii_postgres import factory, TEST_URL
from test_saas_incremento_ii import client, headers, stock

pytestmark=pytest.mark.skipif(not TEST_URL,reason='PostgreSQL desechable no configurado')

def test_simultaneous_reviews_upsert_one_owned_row(client,factory,stock):
    barrier=Barrier(2)
    def write(rating):
        barrier.wait(timeout=10)
        return client.post('/api/v1/products/1/reviews',headers=headers(1),json={'calificacion':rating,'comentario':'Buena calidad y corte'})
    with ThreadPoolExecutor(max_workers=2) as pool:responses=list(pool.map(write,[4,5]))
    assert [r.status_code for r in responses]==[200,200],[r.text for r in responses]
    assert len({r.json()['id'] for r in responses})==1
    response=client.get('/api/v1/products/1/reviews',headers=headers(1)).json()
    assert response['total']==1 and response['promedio'] in [4,5]
    assert not response['mi_resena']['compra_verificada']
    assert client.get('/api/v1/products/1/reviews',headers=headers(2,2,'b')).status_code==404
    with factory.kw['bind'].begin() as connection:
        assert connection.scalar(text('SELECT count(*) FROM resenas_prendas'))==0
        connection.execute(text("SELECT set_config('app.tenant_id','1',true)"))
        assert connection.scalar(text('SELECT count(*) FROM resenas_prendas'))==1
        assert connection.scalar(text("SELECT relrowsecurity AND relforcerowsecurity FROM pg_class WHERE relname='resenas_prendas'"))
    with pytest.raises(IntegrityError), factory.kw['bind'].begin() as connection:
        connection.execute(text("SELECT set_config('app.tenant_id','1',true)"))
        connection.execute(text("UPDATE resenas_prendas SET producto_id=2"))
    with pytest.raises(IntegrityError), factory.kw['bind'].begin() as connection:
        connection.execute(text("SELECT set_config('app.tenant_id','1',true)"))
        connection.execute(text("UPDATE resenas_prendas SET calificacion=0"))

def test_concurrent_downloaded_carts_keep_first_revision(client,factory,stock):
    barrier=Barrier(2)
    def save(quantity):
        barrier.wait(timeout=10)
        return client.put('/api/v1/cart/draft',headers=headers(1),json={'base_items':[],'items':[{'variante_id':1,'cantidad':quantity}]})
    with ThreadPoolExecutor(max_workers=2) as pool:responses=list(pool.map(save,[1,2]))
    assert sorted(r.status_code for r in responses)==[200,409],[r.text for r in responses]
    with factory.kw['bind'].begin() as connection:
        connection.execute(text("SELECT set_config('app.tenant_id','1',true)"))
        assert connection.scalar(text('SELECT count(*) FROM pedidos'))==0
