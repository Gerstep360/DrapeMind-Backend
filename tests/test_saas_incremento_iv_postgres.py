"""Read/write validation only against the disposable PostgreSQL test database."""
from test_saas_incremento_ii_postgres import factory, client, pytestmark
from test_saas_customer_shopping import stocked
from test_saas_incremento_iii import professional
from test_saas_incremento_iv import (
    test_dashboard_and_forecast_enforce_roles_scope_and_empty_data,
    test_forecast_aggregates_real_paid_order_dates,
    test_saved_report_excel_is_scoped_and_requires_plan,
    test_body_asset_never_substitutes_catalog_photo_or_other_tenant,
    test_body_asset_upload_requires_admin_transparency_and_keeps_photos,
)
