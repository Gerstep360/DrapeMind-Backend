from datetime import datetime, timezone
from decimal import Decimal
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError
import pytest
from test_saas_isolation import factory, client, headers
from test_saas_customer_shopping import stocked
from app.models import User, Order, ProductReview
from app.services.store import checkout_cart

pytestmark = pytest.mark.saas_http


def test_review_routes_scope_validation_edit_delete_and_own_review(client, factory, stocked):
    auth = headers(stocked[0])
    body = {"calificacion": 5, "comentario": "  Buena tela y corte  ", "titulo": "Mi opinión"}
    for invalid in ({**body,"calificacion":6},{**body,"calificacion":True},
                    {**body,"comentario":"     "},{**body,"tenant_id":2}):
        assert client.post('/api/v1/products/1/reviews',headers=auth,json=invalid).status_code==422
    first = client.post('/api/v1/products/1/reviews',headers=auth,json=body)
    assert first.status_code==200, first.text
    assert not first.json()['compra_verificada'] and first.json()['comentario']=='Buena tela y corte'
    own=client.get('/api/v1/products/1/my-review',headers=auth)
    assert own.status_code==200 and own.json()['id']==first.json()['id']
    assert client.get('/api/v1/products/1/reviews',headers=headers(2,2,'b')).status_code==404
    assert client.post('/api/v1/products/2/reviews',headers=auth,json=body).status_code==404
    updated=client.post('/api/v1/products/1/reviews',headers=auth,json={**body,'calificacion':3})
    assert updated.json()['id']==first.json()['id']
    with factory(tenant_id=1) as db:assert db.scalar(select(func.count(ProductReview.id)))==1
    result=client.get('/api/v1/products/1/reviews?limit=1&offset=1',headers=auth).json()
    assert result['resenas']==[] and result['total']==1 and result['promedio']==3
    assert result['mi_resena']['id']==first.json()['id']
    assert client.delete('/api/v1/products/1/reviews',headers=auth).status_code==200
    assert client.get('/api/v1/products/1/reviews',headers=auth).json()['total']==0


def test_verified_review_requires_paid_registered_purchase(client, factory, stocked):
    auth=headers(stocked[0]);body={'calificacion':4,'comentario':'Me queda muy bien'}
    with factory(tenant_id=1) as db:
        order=checkout_cart(db,db.get(User,stocked[0]),'RECOJO',None,Decimal(0),None,branch_id=stocked[2])
        order.estado='PAGADO';db.commit();order_id=order.id
    assert not client.post('/api/v1/products/1/reviews',headers=auth,json=body).json()['compra_verificada']
    with factory(tenant_id=1) as db:
        db.get(Order,order_id).paid_at=datetime.now(timezone.utc);db.commit()
    assert client.post('/api/v1/products/1/reviews',headers=auth,json=body).json()['compra_verificada']
    with factory(tenant_id=1) as db:
        db.get(Order,order_id).comprador_registrado=False;db.commit()
    assert not client.post('/api/v1/products/1/reviews',headers=auth,json=body).json()['compra_verificada']


def test_database_rejects_invalid_ratings_outside_http(factory, stocked):
    with factory(tenant_id=1) as db:
        db.add(ProductReview(usuario_id=stocked[0],producto_id=1,calificacion=9,comentario='Opinión inválida'))
        with pytest.raises(IntegrityError):db.commit()
        db.rollback()
