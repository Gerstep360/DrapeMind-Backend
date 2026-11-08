import os
import pytest
from test_saas_incremento_ii_postgres import factory
from test_saas_isolation import client,headers
from test_saas_customer_shopping import stocked
from test_saas_deferred_checkout import (
    provider,body,
    test_saved_card_purchase_is_paid_once_after_lost_reply,
    test_decline_cancels_and_restores_branch_stock_once,
    test_no_card_waits_without_order_or_charge_and_requires_explicit_authorization,
    test_changed_price_no_stock_and_expired_snapshot_never_charge,
    test_3ds_waits_and_cancel_verifies_stripe_before_releasing_stock,
    test_card_and_purchase_are_private_to_user_and_tenant,
    test_cancel_before_lost_submission_cannot_be_charged_on_replay,
    test_another_identifier_cannot_duplicate_an_unfinished_purchase,
    test_setup_checks_stripe_owner_status_and_returns_only_masked_card,
    test_worker_reconciles_persisted_purchase_without_client,
)
pytestmark=pytest.mark.skipif(not os.environ.get('INCREMENTO_II_TEST_DATABASE_URL'),reason='PostgreSQL desechable no configurado')


def test_parallel_reconnection_creates_one_order_and_one_card_charge(client,factory,stocked,provider):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from sqlalchemy import select,func
    from app.models import Order,ProductVariant
    payload=body(stocked,provider);barrier=Barrier(2)
    def attempt(_):
        barrier.wait(timeout=10)
        return client.post('/api/v1/payments/deferred',headers=headers(stocked[0]),json=payload)
    with ThreadPoolExecutor(max_workers=2) as pool:responses=list(pool.map(attempt,range(2)))
    assert all(response.status_code==201 for response in responses),[r.text for r in responses]
    assert len({r.json()['pedido_id'] for r in responses})==1
    with factory(tenant_id=1) as db:
        assert db.scalar(select(func.count(Order.id)))==1
        assert db.get(ProductVariant,stocked[1]).stock_total==9
    assert provider.charges==provider.creates==1
