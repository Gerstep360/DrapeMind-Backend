import os
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from threading import Barrier
import pytest
from sqlalchemy import select,func
from test_saas_incremento_ii_postgres import factory
from test_saas_isolation import client,headers
from test_saas_customer_shopping import stocked
from test_segundo_parcial_revision import (
    test_training_is_persisted_reused_and_isolated_by_company,
    test_checkout_previews_real_branch_stock_without_mutating_order,
    test_cash_desk_card_is_pending_until_stripe_and_qr_is_not_accepted,
)
from app.models import User
from app.segundo_parcial.cu28_machine_learning.cu28_entrenamiento import persisted_forecast
from app.segundo_parcial.cu28_machine_learning.cu28_modelos import DemandModel

pytestmark=pytest.mark.skipif(not os.environ.get('INCREMENTO_II_TEST_DATABASE_URL'),reason='PostgreSQL desechable no configurado')


def test_parallel_model_training_is_serialized_by_company(factory):
    gate=Barrier(2)
    def attempt(_):
        with factory(tenant_id=1) as db:
            user=db.get(User,1);gate.wait(timeout=10)
            return persisted_forecast(db,user,None,[1 if i%7<5 else 15 for i in range(70)],date(2026,1,5))
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(attempt,range(2)))
    assert len({r['entrenamiento']['id'] for r in results})==1
    assert sum(r['entrenamiento']['reutilizado'] for r in results)==1
    with factory(tenant_id=1) as db:assert db.scalar(select(func.count(DemandModel.id)))==1
