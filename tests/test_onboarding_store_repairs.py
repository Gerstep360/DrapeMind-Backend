from decimal import Decimal
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import MagicMock, patch

from fastapi import BackgroundTasks, HTTPException
from app.main import app  # Initialize routers in the application's normal order.
from app.models import Role
from app.schemas.api import OrderStatusUpdate
from app.modules.realidad_aumentada import cu17_utilizar_vestidor_virtual_mediante_realidad_aumentada as ar
from app.modules.carrito_pedidos_y_pagos import cu12_consultar_pedidos_e_historial_de_compras as orders
from app.modules.carrito_pedidos_y_pagos import cu39_gestionar_pedidos_ventas_y_entregas as admin_orders
from app.modules.carrito_pedidos_y_pagos import cu37_registrar_venta_presencial_pago_y_comprobante as pos


class StoreRepairsTests(TestCase):
    def test_recommendation_apply_preserves_old_contract(self):
        from app.schemas.api import RecommendationApply
        from pydantic import ValidationError
        self.assertEqual(RecommendationApply(recomendacion_id=12).recomendacion_id, 12)
        with self.assertRaises(ValidationError):
            RecommendationApply(items=[{'variante_id': 1}])
        with self.assertRaises(ValidationError):
            RecommendationApply(recomendacion_id=12, items=[{'variante_id': 1}], replace_cart=True)
        self.assertTrue(RecommendationApply(items=[{'variante_id': 1}], replace_cart=True).replace_cart)

    def test_recommendation_selection_uses_existing_stock_validation(self):
        from app.schemas.api import RecommendationApply
        from app.modules.inteligencia_artificial_y_asistencia_de_moda import cu24_aplicar_recomendacion_de_ia_al_carrito as recommendations
        db, user = MagicMock(), SimpleNamespace(id=17)
        with patch.object(recommendations, 'replace_cart_items_batch', return_value={'items': []}) as apply:
            result = recommendations.aplicar_recomendacion_carrito(
                RecommendationApply(items=[{'variante_id': 3, 'cantidad': 2}], replace_cart=True), user, db)
        apply.assert_called_once_with(db, 17, [(3, 2)])
        self.assertEqual(result, {'items': []})

    def test_ar_returns_actual_public_schema(self):
        db = MagicMock()
        db.get.return_value = SimpleNamespace(id=12, activo=True, imagenes=['/static/prenda.png'],
            tags_ai=[], nombre='Prenda', material='Algodón', categoria_id=1)
        db.scalars.return_value = [SimpleNamespace(activo=True, talla='M')]
        result = ar.try_on_config(12, user_chest=96, user_waist=80, user_height=170, user=None, db=db)
        self.assertEqual(result.producto_id, 12)
        self.assertEqual(result.asset_url, '/static/prenda.png')
        self.assertIn('M', result.size_metrics)
        self.assertFalse(result.tracking['automatic'])
        self.assertEqual(result.available_sizes, ['M'])

    def test_ar_does_not_invent_asset_or_available_sizes(self):
        db = MagicMock()
        db.get.return_value = SimpleNamespace(id=12, activo=True, imagenes=[],
            tags_ai=[], nombre='Prenda', material='', categoria_id=1)
        db.scalars.return_value = []
        result = ar.try_on_config(12, user_chest=None, user_waist=None, user_height=None, user=None, db=db)
        self.assertFalse(result.supported)
        self.assertIsNone(result.asset_url)
        self.assertEqual(result.available_sizes, [])

    def test_admin_route_reuses_state_machine(self):
        with patch.object(orders, 'update_status', return_value='updated') as update:
            db, staff, tasks = MagicMock(), SimpleNamespace(id=1), BackgroundTasks()
            request = OrderStatusUpdate(estado='LISTO')
            self.assertEqual(admin_orders.actualizar_estado_pedido(1, request, tasks, staff, db), 'updated')
            update.assert_called_once_with(1, request, tasks, staff, db)

    def test_status_cannot_bypass_collection(self):
        db = MagicMock()
        db.get.return_value = SimpleNamespace(estado='PENDIENTE_PAGO', sucursal_id=1)
        with self.assertRaises(HTTPException) as error:
            orders.update_status(1, OrderStatusUpdate(estado='PAGADO'), BackgroundTasks(), SimpleNamespace(rol=Role.ADMIN), db)
        self.assertEqual(error.exception.status_code, 409)
        db.commit.assert_not_called()

    def test_pos_checks_price_before_creating_order(self):
        db = MagicMock()
        db.get.side_effect = [SimpleNamespace(activo=True), SimpleNamespace(activo=True, precio=Decimal('100'))]
        db.scalar.side_effect = [SimpleNamespace(id=5, activo=True, producto_id=1, stock_total=10, stock_reservado=0),
            SimpleNamespace(stock_total=10, stock_reservado=0)]
        request = pos.PosSaleRequest(sucursal_id=1, items=[{'variante_id': 5, 'cantidad': 1, 'precio_unitario': 1}])
        with patch.object(pos, 'staff_can_access_branch', return_value=True), self.assertRaises(HTTPException) as error:
            pos.registrar_venta_pos(request, SimpleNamespace(id=2), db)
        self.assertEqual(error.exception.status_code, 409)
        db.add.assert_not_called()

    def test_pos_rejects_staff_from_another_branch(self):
        db = MagicMock()
        request = pos.PosSaleRequest(sucursal_id=1, items=[{'variante_id': 5, 'cantidad': 1, 'precio_unitario': 100}])
        with patch.object(pos, 'staff_can_access_branch', return_value=False), self.assertRaises(HTTPException) as error:
            pos.registrar_venta_pos(request, SimpleNamespace(id=2), db)
        self.assertEqual(error.exception.status_code, 403)
        db.add.assert_not_called()
