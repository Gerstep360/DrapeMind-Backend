import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from decimal import Decimal

from app.services.ai_tools import _recommend_outfit, _cart, RecommendOutfitArgs, EmptyArgs, ToolContext
from app.services.ai_agent import _cards_from_tool


class OutfitAgentScenariosTests(unittest.TestCase):
    def setUp(self):
        self.db = MagicMock()
        self.user = SimpleNamespace(id=1, nombre="Test User")
        self.context = ToolContext(db=self.db, user=self.user)

    def test_scenario_1_complete_outfit_from_damaris_balconette_bra_returns_cards(self):
        mock_bra = {
            "id": 19277544,
            "nombre": "BOUTIQUE X DAMARIS Navy Blue Underwired Lightly Padded Balconette Bra",
            "precio": 292.61,
            "categoria_id": 10,
            "genero_objetivo": "MUJER",
            "marca": "Marks & Spencer",
            "calidad_nivel": 4,
            "imagenes": ["https://img.test/bra.jpg"],
        }
        mock_bottom = {
            "id": 201,
            "nombre": "Falda Midi Plisada Seda",
            "precio": 310.0,
            "categoria_id": 51,
            "genero_objetivo": "MUJER",
        }
        mock_shoes = {
            "id": 301,
            "nombre": "Sandalias con tacones en punta negra",
            "precio": 350.0,
            "categoria_id": 29,
            "genero_objetivo": "MUJER",
        }
        mock_acc = {
            "id": 401,
            "nombre": "Bolso de Mano Saffiano Atelier",
            "precio": 180.0,
            "categoria_id": 28,
            "genero_objetivo": "MUJER",
        }

        mock_bra_prod = SimpleNamespace(
            id=19277544,
            nombre="BOUTIQUE X DAMARIS Navy Blue Underwired Lightly Padded Balconette Bra",
            precio=Decimal("292.61"),
            categoria_id=10,
            genero_objetivo=SimpleNamespace(value="MUJER"),
            marca="Marks & Spencer",
            calidad_nivel=4,
            activo=True,
            imagenes=["https://img.test/bra.jpg"],
        )
        var_bra = SimpleNamespace(id=1001, producto_id=19277544, color="Azul Marino", talla="34B", imagen="https://img.test/bra.jpg", stock_total=10, stock_reservado=0, activo=True)
        var_bottom = SimpleNamespace(id=1002, producto_id=201, color="Negro", talla="M", imagen="https://img.test/skirt.jpg", stock_total=8, stock_reservado=0, activo=True)
        var_shoes = SimpleNamespace(id=1003, producto_id=301, color="Negro", talla="37", imagen="https://img.test/shoes.jpg", stock_total=5, stock_reservado=0, activo=True)
        var_acc = SimpleNamespace(id=1004, producto_id=401, color="Negro", talla="U", imagen="https://img.test/bag.jpg", stock_total=6, stock_reservado=0, activo=True)

        scalars_mock = MagicMock()
        scalars_mock.all.return_value = [var_bottom, var_shoes, var_acc]
        self.db.scalars.return_value = scalars_mock
        self.db.scalar.side_effect = [mock_bra_prod, var_bra, None]

        with patch("app.services.ai_tools.search_products") as search_mock:
            search_mock.side_effect = [
                [mock_bra],
                [mock_bra, mock_bottom, mock_shoes, mock_acc],
            ]
            raw_args = RecommendOutfitArgs(
                base_product_name="BOUTIQUE X DAMARIS Navy Blue Underwired Lightly Padded Balconette Bra"
            )
            result = _recommend_outfit(self.context, raw_args)

        self.assertIn("seleccion", result)
        cards = _cards_from_tool(self.db, "recommend_outfit", raw_args.model_dump(), result)
        self.assertGreaterEqual(len(cards), 3)
        self.assertEqual(cards[0]["nombre"], "BOUTIQUE X DAMARIS Navy Blue Underwired Lightly Padded Balconette Bra")
        self.assertEqual(cards[0]["accion"], "AGREGAR")
        self.assertTrue(any(c["nombre"] == "Falda Midi Plisada Seda" for c in cards))
        self.assertTrue(any(c["nombre"] == "Sandalias con tacones en punta negra" for c in cards))

    def test_scenario_2_analizar_perchero_empty_cart_returns_showroom_cards(self):
        mock_candidates = [
            {"id": 1, "nombre": "Camisa Oxford Atelier", "precio": 240.0, "categoria_id": 49, "imagenes": ["https://img.test/c1.jpg"]},
            {"id": 2, "nombre": "Pantalón Chino Clásico", "precio": 290.0, "categoria_id": 62, "imagenes": ["https://img.test/p1.jpg"]},
        ]
        var1 = SimpleNamespace(id=11, producto_id=1, color="Blanco", talla="M", imagen="https://img.test/c1.jpg", stock_total=10, stock_reservado=0, activo=True)
        var2 = SimpleNamespace(id=12, producto_id=2, color="Beige", talla="32", imagen="https://img.test/p1.jpg", stock_total=10, stock_reservado=0, activo=True)

        scalars_mock = MagicMock()
        scalars_mock.all.side_effect = [[var1], [var2]]
        self.db.scalars.return_value = scalars_mock

        with patch("app.services.ai_tools.cart_payload", return_value={"items": []}), \
             patch("app.services.ai_tools.search_products", return_value=mock_candidates):
            cart_res = _cart(self.context, EmptyArgs())

        self.assertEqual(cart_res["estado"], "VACIO")
        self.assertGreaterEqual(len(cart_res["sugerencias"]), 1)

        cards = _cards_from_tool(self.db, "get_my_cart", {}, cart_res)
        self.assertGreaterEqual(len(cards), 1)
        self.assertEqual(cards[0]["accion"], "AGREGAR")
        self.assertIn("Sugerencia", cards[0]["motivo"])

    def test_scenario_3_disenar_outfit_a_medida_returns_cards(self):
        mock_candidates = [
            {"id": 10, "nombre": "Camisa Cuello Mao Lino", "precio": 250.0, "categoria_id": 49, "genero_objetivo": "HOMBRE"},
            {"id": 20, "nombre": "Pantalón Lino Sartorial", "precio": 290.0, "categoria_id": 62, "genero_objetivo": "HOMBRE"},
            {"id": 30, "nombre": "Mocasines Cuero Gamuza", "precio": 380.0, "categoria_id": 15, "genero_objetivo": "HOMBRE"},
        ]
        var1 = SimpleNamespace(id=101, producto_id=10, color="Blanco", talla="M", imagen="https://img.test/10.jpg", stock_total=5, stock_reservado=0, activo=True)
        var2 = SimpleNamespace(id=102, producto_id=20, color="Arena", talla="42", imagen="https://img.test/20.jpg", stock_total=5, stock_reservado=0, activo=True)
        var3 = SimpleNamespace(id=103, producto_id=30, color="Café", talla="42", imagen="https://img.test/30.jpg", stock_total=5, stock_reservado=0, activo=True)

        scalars_mock = MagicMock()
        scalars_mock.all.return_value = [var1, var2, var3]
        self.db.scalars.return_value = scalars_mock
        self.db.scalar.return_value = None

        with patch("app.services.ai_tools.search_products", return_value=mock_candidates):
            raw_args = RecommendOutfitArgs(
                occasion="casual elegante",
                gender="HOMBRE",
                max_budget=1000.0,
            )
            result = _recommend_outfit(self.context, raw_args)

        cards = _cards_from_tool(self.db, "recommend_outfit", raw_args.model_dump(), result)
        self.assertEqual(len(cards), 3)
        self.assertEqual(cards[0]["nombre"], "Camisa Cuello Mao Lino")
        self.assertEqual(cards[1]["nombre"], "Pantalón Lino Sartorial")
        self.assertEqual(cards[2]["nombre"], "Mocasines Cuero Gamuza")
        self.assertTrue(all(c["accion"] == "AGREGAR" for c in cards))

    def test_scenario_4_look_por_presupuesto_keeps_all_three_items(self):
        mock_candidates = [
            {"id": 1, "nombre": "Polera Pima Básica Atelier", "precio": 110.0, "categoria_id": 64, "genero_objetivo": "UNISEX"},
            {"id": 2, "nombre": "Bermuda Chino Lino", "precio": 150.0, "categoria_id": 50, "genero_objetivo": "UNISEX"},
            {"id": 3, "nombre": "Alpargatas Clásicas", "precio": 130.0, "categoria_id": 23, "genero_objetivo": "UNISEX"},
        ]
        var1 = SimpleNamespace(id=11, producto_id=1, color="Negro", talla="L", imagen="https://img.test/1.jpg", stock_total=5, stock_reservado=0, activo=True)
        var2 = SimpleNamespace(id=12, producto_id=2, color="Gris", talla="M", imagen="https://img.test/2.jpg", stock_total=5, stock_reservado=0, activo=True)
        var3 = SimpleNamespace(id=13, producto_id=3, color="Azul", talla="42", imagen="https://img.test/3.jpg", stock_total=5, stock_reservado=0, activo=True)

        scalars_mock = MagicMock()
        scalars_mock.all.return_value = [var1, var2, var3]
        self.db.scalars.return_value = scalars_mock
        self.db.scalar.return_value = None

        with patch("app.services.ai_tools.search_products", return_value=mock_candidates):
            raw_args = RecommendOutfitArgs(
                occasion="moderno y elegante",
                max_budget=400.0,
            )
            result = _recommend_outfit(self.context, raw_args)

        cards = _cards_from_tool(self.db, "recommend_outfit", raw_args.model_dump(), result)
        self.assertEqual(len(cards), 3)
        self.assertLessEqual(result["seleccion_total"], 400.0)
        self.assertTrue(all(c["accion"] == "AGREGAR" for c in cards))
