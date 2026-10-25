"""Segundo parcial: CU-01..CU-06 (different from historical cuNN module names)."""
from unittest.mock import Mock
import pytest
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError
from test_saas_isolation import factory, client, headers
from app.core.security import create_access_token
from app.core.tenancy import system_scope
from app.models import User, Role, UserStatus
from app.models.saas import Tenant, TenantSubscription


def platform_headers():
    token,_=create_access_token(3,'ADMIN',platform=True)
    return {'Authorization':'Bearer '+token}


def company_data():
    return {'name':'Empresa ICONIX','slug':'iconix-test','admin_name':'Admin ICONIX','admin_email':'admin@example.com','admin_password':'Only-test-fixture-123!','plan_id':1}


def test_i1_cu01_duplicate_slug_is_conflict(client):
    assert client.post('/api/v1/saas/tenants',headers=platform_headers(),json=company_data()).status_code==201
    assert client.post('/api/v1/saas/tenants',headers=platform_headers(),json=company_data()).status_code==409


def test_i1_cu01_mid_transaction_failure_rolls_back_company(client,factory,monkeypatch):
    from app.api.v1.endpoints import saas
    monkeypatch.setattr(saas,'hash_password',Mock(side_effect=RuntimeError('injected test failure')))
    assert client.post('/api/v1/saas/tenants',headers=platform_headers(),json=company_data()).status_code==500
    with factory() as db,system_scope(db):
        assert db.scalar(select(Tenant.id).where(Tenant.slug=='iconix-test')) is None
        assert db.scalar(select(func.count(TenantSubscription.id)))==2


def test_i1_cu01_integrity_race_returns_conflict_and_rolls_back(client,factory,monkeypatch):
    from app.api.v1.endpoints import saas
    monkeypatch.setattr(saas,'hash_password',Mock(side_effect=IntegrityError('fixture',{},Exception('unique conflict'))))
    assert client.post('/api/v1/saas/tenants',headers=platform_headers(),json=company_data()).status_code==409
    with factory() as db:
        assert db.scalar(select(Tenant.id).where(Tenant.slug=='iconix-test')) is None


@pytest.mark.parametrize('change',[{'rol':'CLIENTE'},{'estado':'BLOQUEADO'},{'rol':'CAJERO','estado':'INACTIVO'}])
def test_i1_cu06_last_active_admin_cannot_be_removed(client,change):
    result=client.patch('/api/v1/admin/users/1',headers=headers(),json=change)
    assert result.status_code==409
    assert client.get('/api/v1/admin/users',headers=headers()).status_code==200


def test_i1_cu06_admin_changes_are_tenant_scoped(client):
    assert client.patch('/api/v1/admin/users/2',headers=headers(),json={'estado':'BLOQUEADO'}).status_code==404
    assert client.delete('/api/v1/admin/users/2',headers=headers()).status_code==404


def test_i1_cu06_employee_password_and_reserved_fields(client):
    data={'nombre':'Empleado ICONIX','email':'Empleado@Example.com','password':'Employee-fixture-123!','rol':'VENDEDOR','estado':'ACTIVO'}
    assert client.post('/api/v1/admin/users',headers=headers(),json={**data,'is_platform_admin':True}).status_code==422
    assert client.post('/api/v1/admin/users',headers=headers(),json={**data,'tenant_id':2}).status_code==422
    result=client.post('/api/v1/admin/users',headers=headers(),json=data)
    assert result.status_code==201 and result.json()['email']=='empleado@example.com'
    assert 'password_hash' not in result.json() and 'password' not in result.json()
    assert client.post('/api/v1/admin/users',headers=headers(),json={**data,'email':'EMPLEADO@example.com'}).status_code==409
    employee=headers(result.json()['id'],1,'a')
    assert client.patch('/api/v1/admin/users/1',headers=employee,json={'rol':'CLIENTE'}).status_code==403


def test_i1_cu06_another_admin_can_take_over_without_locking_company(client):
    result=client.post('/api/v1/admin/users',headers=headers(),json={'nombre':'Segundo admin','email':'second@example.com','password':'Only-test-fixture-123!','rol':'ADMIN'})
    assert result.status_code==201
    assert client.patch('/api/v1/admin/users/1',headers=headers(),json={'rol':'VENDEDOR'}).status_code==200
    assert client.get('/api/v1/admin/users',headers=headers()).status_code==403
    second=headers(result.json()['id'],1,'a')
    assert client.get('/api/v1/admin/users',headers=second).status_code==200


def test_i1_cu06_status_toggle_matches_database_enum(client):
    created=client.post('/api/v1/admin/users',headers=headers(),json={'nombre':'Employee','email':'employee@example.com','password':'Employee-fixture-123!','rol':'VENDEDOR'})
    id=created.json()['id']
    assert client.delete(f'/api/v1/admin/users/{id}',headers=headers()).json()['estado']=='BLOQUEADO'
    assert client.delete(f'/api/v1/admin/users/{id}',headers=headers()).json()['estado']=='ACTIVO'
