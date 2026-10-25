"""Segundo parcial CU-07..CU-10: existing modules, owned resources and business rules."""
from decimal import Decimal
from types import SimpleNamespace
import pytest
from test_saas_isolation import factory,client,headers
from app.core.tenancy import system_scope
from app.models import User,Role,UserStatus,BranchStaff,BranchStock,ProductVariant,InventoryMovement
from app.services.promotion_rules import basket_discount
from sqlalchemy import select


@pytest.fixture(autouse=True)
def no_external_notifications(monkeypatch):
    from app.services import push_notifications
    async def noop(*args,**kwargs):return None
    monkeypatch.setattr(push_notifications,'dispatch_notification',noop)


@pytest.fixture
def stocked(factory):
    with factory() as db,system_scope(db):
        db.add(User(id=4,tenant_id=1,nombre='Encargado',email='manager@example.com',password_hash='fixture',rol=Role.ENCARGADO,estado=UserStatus.ACTIVO))
        db.add_all([ProductVariant(id=i,tenant_id=i,producto_id=i,sku='SAME-SKU',color='Negro',talla='M',stock_total=10,stock_reservado=2) for i in (1,2)])
        db.flush()
        db.add_all([BranchStock(tenant_id=i,sucursal_id=i,variante_id=i,stock_total=10,stock_reservado=2) for i in (1,2)])
        db.add(BranchStaff(tenant_id=1,usuario_id=4,sucursal_id=1,activo=True));db.commit()


def test_cu07_plan_quota_applies_to_create_and_reactivate(client):
    payload={'ciudad_id':1,'codigo':'NORTE','nombre':'Norte','direccion':'Calle principal','activo':True}
    created=client.post('/api/v1/branches',headers=headers(),json=payload);assert created.status_code==201
    assert client.post('/api/v1/branches',headers=headers(),json={**payload,'codigo':'TERCERA'}).status_code==409
    id=created.json()['id'];assert client.delete(f'/api/v1/branches/{id}',headers=headers()).status_code==200
    assert client.post('/api/v1/branches',headers=headers(),json={**payload,'codigo':'TERCERA'}).status_code==201
    assert client.delete(f'/api/v1/branches/{id}',headers=headers()).status_code==409


def test_cu07_city_must_belong_to_same_company(client):
    assert client.post('/api/v1/branches',headers=headers(),json={'ciudad_id':2,'codigo':'CROSS','nombre':'Otra','direccion':'Fuera de empresa'}).status_code==404


def test_cu08_category_cycles_foreign_parents_and_duplicates(client):
    payload={'nombre':'Hija','slug':'hija','parent_id':1}
    child=client.post('/api/v1/admin/categories',headers=headers(),json=payload);assert child.status_code==201
    id=child.json()['id']
    assert client.put('/api/v1/admin/categories/1',headers=headers(),json={'nombre':'Camisas','slug':'camisas','parent_id':id}).status_code==409
    assert client.post('/api/v1/admin/categories',headers=headers(),json={**payload,'slug':'cross','parent_id':2}).status_code==404
    assert client.put(f'/api/v1/admin/categories/{id}',headers=headers(),json={**payload,'slug':'camisas'}).status_code==409


def test_cu08_inactive_categories_can_be_managed_but_not_read_by_staff(client,stocked):
    assert client.delete('/api/v1/admin/categories/1',headers=headers()).status_code==200
    rows=client.get('/api/v1/admin/categories?include_inactive=true',headers=headers()).json()
    assert any(r['id']==1 and not r['activo'] for r in rows)
    assert client.get('/api/v1/admin/categories?include_inactive=true',headers=headers(4)).status_code==403


def test_cu08_variant_cannot_destroy_reserved_or_distributed_stock(client,stocked):
    payload={'sku':'SAME-SKU','color':'Negro','talla':'M','stock_total':1}
    assert client.put('/api/v1/admin/variants/1',headers=headers(),json=payload).status_code==409
    assert client.put('/api/v1/admin/variants/1',headers=headers(),json={**payload,'stock_total':8}).status_code==409
    assert client.delete('/api/v1/admin/variants/1',headers=headers()).status_code==409
    assert client.put('/api/v1/admin/variants/2',headers=headers(),json=payload).status_code==404


def test_cu09_manager_updates_assigned_stock_and_kardex_only(client,factory,stocked):
    auth=headers(4)
    result=client.put('/api/v1/branches/1/stock?observacion=Conteo%20verificado',headers=auth,json={'variante_id':1,'stock_total':12})
    assert result.status_code==200,result.text
    assert client.put('/api/v1/branches/2/stock',headers=auth,json={'variante_id':1,'stock_total':12}).status_code in (403,404)
    assert client.put('/api/v1/branches/1/stock',headers=auth,json={'variante_id':1,'stock_total':1}).status_code==409
    with factory(tenant_id=1) as db:
        assert db.get(ProductVariant,1).stock_total==12
        movements=list(db.scalars(select(InventoryMovement)))
        assert len(movements)==1 and movements[0].stock_total_anterior==10 and movements[0].stock_total_nuevo==12


def test_cu09_global_adjustment_cannot_overwrite_branch_inventory(client,stocked):
    payload={'variante_id':1,'nuevo_stock_total':8,'observacion':'Conteo de tienda'}
    assert client.post('/api/v1/admin/inventory/adjustments',headers=headers(),json=payload).status_code==409
    assert client.post('/api/v1/admin/inventory/adjustments',headers=headers(),json={**payload,'sucursal_id':1,'tipo':'ENTRADA'}).status_code==409


def test_cu10_price_changes_use_owned_product(client):
    payload={'categoria_id':1,'nombre':'Prenda actualizada','precio':'175.00'}
    assert client.put('/api/v1/admin/products/1',headers=headers(),json=payload).status_code==200
    product=client.get('/api/v1/catalog/products/1',headers=headers()).json()
    assert Decimal(str(product['precio']))==Decimal('175.00')
    assert client.put('/api/v1/admin/products/2',headers=headers(),json=payload).status_code==404


def test_cu10_promotion_limits_dates_and_ownership(client):
    base={'codigo':'PROMO','tipo_descuento':'PORCENTAJE','valor_descuento':'20'}
    assert client.post('/api/v1/admin/promotions',headers=headers(),json={**base,'valor_descuento':'101'}).status_code==422
    assert client.post('/api/v1/admin/promotions',headers=headers(),json={**base,'fecha_inicio':'2027-01-02','fecha_fin':'2027-01-01'}).status_code==422
    assert client.post('/api/v1/admin/promotions',headers=headers(),json={**base,'producto_id':2}).status_code==404
    assert client.post('/api/v1/admin/promotions',headers=headers(),json=base).status_code==201
    assert client.post('/api/v1/admin/promotions',headers=headers(2,2,'b'),json=base).status_code==201


def test_cu10_discount_uses_eligible_product_and_actual_pairs():
    promo=SimpleNamespace(producto_id=1,tipo_descuento='PORCENTAJE',valor_descuento=Decimal('20'))
    assert basket_discount(promo,[(1,2,Decimal('100')),(2,1,Decimal('1000'))])==Decimal('40.00')
    promo.tipo_descuento='DOS_POR_UNO'
    assert basket_discount(promo,[(1,3,Decimal('100'))])==Decimal('100.00')
    assert basket_discount(promo,[(1,1,Decimal('100'))])==Decimal('0.00')
    promo.tipo_descuento='MONTO_FIJO';promo.valor_descuento=Decimal('999')
    assert basket_discount(promo,[(1,1,Decimal('100')),(2,1,Decimal('1000'))])==Decimal('100.00')
