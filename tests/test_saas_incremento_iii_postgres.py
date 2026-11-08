"""CU-21 a CU-25 sobre PostgreSQL desechable con RLS sin bypass."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4
from decimal import Decimal
from sqlalchemy import select, func, text
from test_saas_incremento_ii_postgres import factory, client, pytestmark
from test_saas_customer_shopping import stocked
from test_saas_incremento_iii import professional, checkout, paid, test_checkout_reply_loss_recovers_same_order_and_never_reduces_stock_twice, test_receipt_pdf_requires_payment_owner_or_assigned_branch, test_customer_can_cancel_pending_checkout_and_stock_returns_once, test_report_plan_role_scope_and_input_validation, test_report_natural_language_is_grounded_saved_and_tenant_scoped, test_nvidia_unavailable_creates_no_fabricated_report, test_delivery_price_comes_from_server_not_client
from app.services.store import checkout_cart
from app.models import User, Order, ProductVariant

def test_concurrent_checkout_uuid_has_one_order_and_one_stock_decrement(factory,stocked):
 uid,vid,branch=stocked;operation=str(uuid4());barrier=Barrier(2)
 def worker():
  with factory(tenant_id=1) as db:
   user=db.get(User,uid);barrier.wait(timeout=15)
   return checkout_cart(db,user,'RECOJO',None,Decimal('0'),None,branch_id=branch,operation_id=operation,payload_hash='same-body').id
 with ThreadPoolExecutor(max_workers=2) as pool:ids=list(pool.map(lambda _:worker(),range(2)))
 assert ids[0]==ids[1]
 with factory(tenant_id=1) as db:
  assert db.scalar(select(func.count(Order.id)))==1 and db.get(ProductVariant,vid).stock_total==9
  for table in ('checkout_confirmaciones','reportes_empresariales'):
   r=db.connection().execute(text('SELECT relrowsecurity,relforcerowsecurity FROM pg_class WHERE relname=:table'),{'table':table}).one()
   assert all(r)
