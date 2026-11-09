from sqlalchemy import select, func
from decimal import Decimal
from test_saas_isolation import factory, client, headers
from test_saas_customer_shopping import stocked
from app.models import CartItem, Order, BranchStock


def test_cart_draft_reconciles_once_without_reserving_stock(client,factory,stocked):
    auth=headers(stocked[0]);variant=stocked[1]
    payload={'base_items':[{'variante_id':variant,'cantidad':3}],'items':[{'variante_id':variant,'cantidad':2}]}
    first=client.put('/api/v1/cart/draft',headers=auth,json=payload)
    assert first.status_code==200,first.text
    second=client.put('/api/v1/cart/draft',headers=auth,json=payload)
    assert second.status_code==200 and second.json()['total_items']==2
    assert Decimal(first.json()['subtotal'])==Decimal('200.00')
    with factory(tenant_id=1) as db:
        assert db.scalar(select(func.count(CartItem.id)))==1
        assert db.scalar(select(func.count(Order.id)))==0
        assert db.scalar(select(BranchStock.stock_total).where(BranchStock.sucursal_id==stocked[2]))==10
    clear={'base_items':payload['items'],'items':[]}
    assert client.put('/api/v1/cart/draft',headers=auth,json=clear).json()['total_items']==0


def test_cart_draft_does_not_overwrite_other_device_or_company(client,factory,stocked):
    auth=headers(stocked[0]);variant=stocked[1]
    original=client.get('/api/v1/cart',headers=auth).json()['items'][0]
    assert client.patch('/api/v1/cart/items/'+str(original['id']),headers=auth,json={'cantidad':4}).status_code==200
    stale={'base_items':[{'variante_id':variant,'cantidad':3}],'items':[{'variante_id':variant,'cantidad':1}]}
    response=client.put('/api/v1/cart/draft',headers=auth,json=stale)
    assert response.status_code==409 and response.json()['detail']['code']=='CART_CHANGED'
    assert client.get('/api/v1/cart',headers=auth).json()['total_items']==4
    assert client.put('/api/v1/cart/draft',headers=headers(2,2,'b'),json={'base_items':[],'items':stale['items']}).status_code==404
    assert client.put('/api/v1/cart/draft',headers=auth,json={**stale,'tenant_id':2}).status_code==422
