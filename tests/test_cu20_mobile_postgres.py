"""Reuse financial recovery contracts against migrated PostgreSQL with forced RLS."""
import pytest
from test_saas_incremento_ii_postgres import factory, TEST_URL
from test_saas_incremento_ii import client, stock
from test_saas_incremento_ii_retail import clerk
from test_cu20_mobile_recovery import (
    test_stripe_failure_does_not_fabricate_cash_or_change_inventory,
    test_pending_refund_is_truthful_and_webhook_reconciles_current_state,
    test_missing_stripe_configuration_cannot_approve_refund,
    test_failed_or_unknown_refund_is_not_success,
    test_refund_result_is_bound_to_specific_exchange,
)
pytestmark=pytest.mark.skipif(not TEST_URL, reason='PostgreSQL desechable no configurado')
