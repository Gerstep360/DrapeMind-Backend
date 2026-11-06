from datetime import date
from io import BytesIO
from zipfile import ZipFile
from unittest.mock import AsyncMock
import json
from xml.etree import ElementTree as ET
from test_saas_isolation import factory, client, headers
from test_saas_customer_shopping import stocked
from test_saas_incremento_iii import professional
from app.incrementos.incremento_iv.forecast import forecast
from app.incrementos.incremento_iv.spreadsheet import workbook


def test_export_text_never_becomes_formula_and_xml_is_valid():
    with ZipFile(BytesIO(workbook([['=HYPERLINK("https://example.com")', '<tag>&'], ['Unidades', 12]]))) as z:
        assert z.testzip() is None
        for name in z.namelist():
            ET.fromstring(z.read(name))
        sheet = ET.fromstring(z.read('xl/worksheets/sheet1.xml'))
        assert not sheet.findall('.//{*}f')
        assert sheet.find('.//{*}t').text.startswith('=HYPERLINK')
        assert sheet.find('.//{*}v').text == '12'


def test_forecast_requires_history_and_validates_chronologically():
    assert forecast([1] * 41, date(2026, 1, 1))['estado'] == 'DATOS_INSUFICIENTES'
    assert forecast([0] * 60, date(2026, 1, 1))['predicciones'] == []
    result = forecast(list(range(60)), date(2026, 1, 1))
    assert result['modelo'] == 'Regresión lineal'
    assert result['predicciones'][0]['pedidos_estimados'] == 60
    assert result['validacion']['mae_regresion'] == 0
    assert len(result['predicciones']) == 7
    assert sum(row['pedidos'] for row in result['patron_semanal']) == sum(range(60))


def test_altair_confirmed_budget_overrides_saved_habitual_budget(monkeypatch):
    from types import SimpleNamespace
    from app.services import personal_shopping as shop
    monkeypatch.setattr(shop, 'shopping_context', lambda db, user: {'profile': {'presupuesto_habitual': '100'}, 'city': 'La Paz'})
    context = SimpleNamespace(db=None, user=None, preferences={'budget': '250'})
    assert shop._preferences(context, shop.DiscoverArgs())['max_price'] == '250'
    assert shop._preferences(context, shop.DiscoverArgs(max_price=80))['max_price'] == 80
    assert shop._preferences(context, shop.DiscoverArgs(use_profile=False))['max_price'] is None


def test_dashboard_and_forecast_enforce_roles_scope_and_empty_data(client, factory, stocked):
    uid, _, branch = stocked
    assert client.get('/api/v1/business-dashboard', headers=headers(uid)).status_code == 403
    result = client.get('/api/v1/business-dashboard', headers=headers())
    assert result.status_code == 200
    assert result.json()['pedidos_pagados'] == 0
    assert client.get('/api/v1/business-dashboard?days=367', headers=headers()).status_code == 422
    assert client.get(f'/api/v1/business-predictions?sucursal_id={branch}', headers=headers(2, 2, 'b')).status_code == 404
    result = client.get('/api/v1/business-predictions', headers=headers())
    assert result.status_code == 200
    assert result.json()['estado'] == 'DATOS_INSUFICIENTES'
    assert result.json()['predicciones'] == []


def test_forecast_aggregates_real_paid_order_dates(client, factory):
    from datetime import datetime, timezone, timedelta
    from app.models import Order
    from uuid import uuid4
    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    with factory(tenant_id=1) as db:
        for i in range(1, 61):
            db.add(Order(codigo_publico=uuid4(), usuario_id=1, estado='ENTREGADO', canal='WEB', tipo_entrega='RECOJO', paid_at=today-timedelta(days=i)))
        db.commit()
    result = client.get('/api/v1/business-predictions', headers=headers())
    assert result.status_code == 200, result.text
    data = result.json()
    assert data['estado'] == 'DISPONIBLE'
    assert data['observaciones'] == 60
    assert data['pedidos_observados'] == 60
    assert all(row['pedidos_estimados'] == 1 for row in data['predicciones'])


def test_saved_report_excel_is_scoped_and_requires_plan(client, factory, professional, monkeypatch):
    monkeypatch.setattr('app.incrementos.incremento_iii.router.call_nvidia', AsyncMock(return_value=(json.dumps({'titulo': 'Reporte', 'analisis': 'No hay cobros.', 'recomendaciones': ['Revisar catálogo']}), {})))
    result = client.post('/api/v1/business-reports', headers=headers(), json={'consulta': 'Revisa las ventas de hoy'})
    assert result.status_code == 201, result.text
    url = f"/api/v1/business-reports/{result.json()['id']}/xlsx"
    response = client.get(url, headers=headers())
    assert response.status_code == 200
    assert response.content.startswith(b'PK')
    assert client.get(url, headers=headers(2, 2, 'b')).status_code == 404


def test_body_asset_never_substitutes_catalog_photo_or_other_tenant(client, factory, stocked):
    from app.models import Product, ProductVariant
    uid, vid, _ = stocked
    with factory(tenant_id=1) as db:
        pid = db.get(ProductVariant, vid).producto_id
        product = db.get(Product, pid)
        product.imagenes = [{'url': 'https://example.com/catalog.jpg'}]
        db.commit()
    path = f'/api/v1/ar/products/{pid}/body-asset'
    assert client.get(path, headers=headers(uid)).status_code == 409
    with factory(tenant_id=1) as db:
        db.get(Product, pid).imagenes = [{'ar_asset': '/static/products/top.png', 'ar_category': 'upper_body'}]
        db.commit()
    result = client.get(path, headers=headers(uid))
    assert result.status_code == 200
    assert result.json()['asset_url'] == '/static/products/top.png'
    assert client.get(path, headers=headers(2, 2, 'b')).status_code == 404


def test_body_asset_upload_requires_admin_transparency_and_keeps_photos(client, factory, stocked, tmp_path, monkeypatch):
    from PIL import Image
    from app.models import Product, ProductVariant
    monkeypatch.setattr('app.modules.catalogo_y_comercializacion.cu29_gestionar_productos_de_ropa.STATIC_PRODUCTS_DIR', tmp_path)
    uid, vid, _ = stocked
    with factory(tenant_id=1) as db:
        pid = db.get(ProductVariant, vid).producto_id
        db.get(Product, pid).imagenes = ['https://example.com/photo.jpg']
        db.commit()
    path = f'/api/v1/ar/products/{pid}/body-asset'
    def png(transparent):
        image = Image.new('RGBA', (80, 80), (0, 0, 0, 0 if transparent else 255))
        image.paste((0, 100, 0, 255), (20, 20, 60, 60))
        buffer = BytesIO(); image.save(buffer, format='PNG'); return buffer.getvalue()
    assert client.post(path, headers=headers(uid), files={'file': ('top.png', png(True), 'image/png')}).status_code == 403
    assert client.post(path, headers=headers(), files={'file': ('top.png', png(False), 'image/png')}).status_code == 422
    response = client.post(path, headers=headers(), files={'file': ('top.png', png(True), 'image/png')})
    assert response.status_code == 200, response.text
    assert client.get(path, headers=headers(uid)).json()['asset_url'] == response.json()['ar_asset']
    assert len(list(tmp_path.rglob('*.png'))) == 1
    with factory(tenant_id=1) as db:
        assert db.get(Product, pid).imagenes[0] == 'https://example.com/photo.jpg'
