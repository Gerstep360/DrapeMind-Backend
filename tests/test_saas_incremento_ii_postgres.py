"""Opt-in: migrated disposable PostgreSQL, real RLS and simultaneous HTTP retries.

Use INCREMENTO_II_TEST_DATABASE_URL with a database named incremento_ii_test.
Never points at the application database. Requires migrations already applied.
"""
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from threading import Barrier
import pytest
from sqlalchemy import create_engine, text, select, func
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker
from app.db.tenant_session import TenantSession
from app.core.tenancy import system_scope
from app.models import User, UserStatus, Role, Category, City, Product, Branch, Reservation, ProductVariant
from app.models.saas import Tenant, SaaSPlan, TenantSubscription
from test_saas_incremento_ii import (
    client, headers, stock, offline_request,
    test_cu12_bundle_is_owned_complete_and_without_private_costs,
    test_cu12_plan_and_role_are_checked,
    test_cu14_confirmation_is_atomic_and_idempotent,
    test_cu14_stock_conflict_keeps_server_unchanged_and_can_retry,
    test_cu14_rechecks_branch_ownership_and_rejects_injected_price,
    test_cu14_multiple_lines_do_not_leave_partial_reservations,
    test_cu14_uses_current_database_price_after_download,
    test_cu11_supplier_portal_and_receiving_updates_inventory_once,
    test_cu11_cancel_confirmed_restores_offer_without_entering_stock,
)
from test_saas_incremento_ii_retail import (
    clerk, sale_body, sync,
    test_cash_sale_idempotent_and_isolated,
    test_price_conflict_is_audited_and_only_manager_can_accept_saved_price,
    test_rejection_requires_refund_confirmation_and_remains_terminal,
    test_attend_and_cash_pickup_consumes_reserved_units_once,
    test_exchange_partial_return_credit_and_duplicate_protection,
    test_closed_branch_cash_conflict_can_be_refunded_and_audited,
    test_exchange_refund_preserves_net_revenue,
    test_conflicted_reservation_cancel_is_visible_to_manager_and_terminal,
    test_cash_multiple_lines_roll_back_without_partial_sale,
    test_result_lookup_is_scoped_to_the_authenticated_owner,
    test_expired_reservation_releases_branch_and_global_inventory,
)

TEST_URL = os.environ.get('INCREMENTO_II_TEST_DATABASE_URL')
pytestmark = pytest.mark.skipif(not TEST_URL, reason='PostgreSQL desechable no configurado')


@pytest.fixture
def factory():
    url = make_url(TEST_URL)
    assert url.database == 'incremento_ii_test', 'Only the disposable integration database is permitted'
    admin = create_engine(url)
    with admin.begin() as connection:
        assert connection.scalar(text('SELECT version_num FROM alembic_version')) == '20261028_02'
        tables = connection.scalars(text("SELECT tablename FROM pg_tables WHERE schemaname='public' AND tablename!='alembic_version'")).all()
        connection.exec_driver_sql('TRUNCATE '+','.join('"'+t+'"' for t in tables)+' RESTART IDENTITY CASCADE')
        connection.exec_driver_sql("DO $$ BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname='incremento_ii_runtime') THEN CREATE ROLE incremento_ii_runtime LOGIN NOSUPERUSER NOBYPASSRLS; END IF; END $$")
        connection.exec_driver_sql('GRANT USAGE ON SCHEMA public TO incremento_ii_runtime')
        connection.exec_driver_sql('GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA public TO incremento_ii_runtime')
        connection.exec_driver_sql('GRANT USAGE,SELECT ON ALL SEQUENCES IN SCHEMA public TO incremento_ii_runtime')
    seed = sessionmaker(bind=admin, class_=TenantSession, expire_on_commit=False, autoflush=False)
    now = datetime.now(timezone.utc)
    with seed() as db, system_scope(db):
        db.add_all([Tenant(id=i, name=f'Empresa {i}', slug=slug) for i, slug in ((1,'a'),(2,'b'))])
        db.add_all([SaaSPlan(id=1,code='BASIC',name='Básico',max_branches=2,ai_reports=False),
                    SaaSPlan(id=2,code='PRO',name='Profesional',max_branches=10,ai_reports=True)])
        db.flush()
        for i in (1,2):
            db.add_all([
                TenantSubscription(tenant_id=i,plan_id=i,status='ACTIVE',source='ADMINISTRATIVE',starts_at=now,ends_at=now+timedelta(days=30)),
                User(id=i,tenant_id=i,nombre=f'Admin {i}',email='same@example.com',password_hash='fixture',rol=Role.ADMIN,estado=UserStatus.ACTIVO),
                Category(id=i,tenant_id=i,nombre='Camisas',slug='camisas'),
                City(id=i,tenant_id=i,nombre='La Paz',departamento='La Paz')])
        db.flush()
        for i in (1,2):
            db.add_all([Product(id=i,tenant_id=i,categoria_id=i,nombre=f'Prenda {i}',precio=Decimal('100'),imagenes=[],activo=True),
                        Branch(id=i,tenant_id=i,ciudad_id=i,nombre='Centro',codigo='CENTRO',direccion='Principal',activo=True)])
        db.commit()
    with admin.begin() as connection:
        for sequence in connection.scalars(text("SELECT sequencename FROM pg_sequences WHERE schemaname='public'")).all():
            connection.execute(text("SELECT setval(CAST(:seq AS regclass), 1000, true)"), {'seq':sequence})
    runtime = create_engine(url.set(username='incremento_ii_runtime', password=None),pool_size=6)
    try:
        yield sessionmaker(bind=runtime,class_=TenantSession,expire_on_commit=False,autoflush=False)
    finally:
        runtime.dispose()
        admin.dispose()


def test_rls_blocks_unscoped_raw_sql_and_other_company(factory, stock):
    engine = factory.kw['bind']
    with engine.begin() as connection:
        assert connection.scalar(text('SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname=current_user')) is False
        assert connection.scalar(text('SELECT count(*) FROM variantes_producto')) == 0
        connection.execute(text("SELECT set_config('app.tenant_id','1',true)"))
        assert connection.scalars(text('SELECT id FROM variantes_producto')).all() == [1]


def test_simultaneous_retry_commits_one_reservation(client, stock, factory):
    payload = offline_request()
    barrier = Barrier(2)
    def send():
        barrier.wait(timeout=10)
        return client.post('/api/v1/offline/reservations',headers=headers(4),json=payload)
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _:send(), range(2)))
    assert sorted(r.status_code for r in responses) == [200,201], [r.text for r in responses]
    assert len({r.json()['reservation']['id'] for r in responses}) == 1
    with factory(tenant_id=1) as db:
        assert db.scalar(select(func.count(Reservation.id))) == 1
        assert db.get(ProductVariant,1).stock_reservado == 2


def test_two_buyers_cannot_reserve_more_than_branch_stock(client, stock, factory):
    with factory(tenant_id=1) as db:
        db.add(User(id=6, nombre='Otro cliente',email='second@example.com',password_hash='fixture',rol=Role.CLIENTE,estado=UserStatus.ACTIVO))
        db.commit()
    barrier=Barrier(2)
    def send(user_id):
        payload=offline_request()
        payload['items'][0]['cantidad']=7
        barrier.wait(timeout=10)
        return client.post('/api/v1/offline/reservations',headers=headers(user_id),json=payload)
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses=list(pool.map(send,[4,6]))
    assert sorted(r.status_code for r in responses)==[201,409],[r.text for r in responses]
    with factory(tenant_id=1) as db:
        assert db.scalar(select(func.count(Reservation.id)))==1
        assert db.get(ProductVariant,1).stock_reservado==7


def test_cash_sale_simultaneous_retries_never_double_charge(client,clerk,factory):
    body=sale_body();barrier=Barrier(2)
    def send():
        barrier.wait(timeout=10)
        return sync(client,clerk,body)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda _:send(),range(2)))
    assert all(r.status_code==200 and r.json()['estado']=='CONFIRMED' for r in results),[r.text for r in results]
    assert len({r.json()['resultado']['sale']['pedido_id'] for r in results})==1
    from app.models import Order,Payment
    with factory(tenant_id=1) as db:
        assert db.get(ProductVariant,1).stock_total==8
        assert db.scalar(select(func.count(Order.id)))==1
        assert db.scalar(select(func.count(Payment.id)))==1
