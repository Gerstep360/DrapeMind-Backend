import pytest
from decimal import Decimal
from unittest.mock import MagicMock
from types import SimpleNamespace
from fastapi import HTTPException

from scripts.db.seed.seed_data import sample_balanced_products
from app.modules.inteligencia_artificial_y_asistencia_de_moda.cu26_generar_reportes_empresariales_mediante_ia import (
    _sintetizar_reporte_directivo_resiliente,
    ReporteDinamicoIA,
)
from app.modules.inteligencia_artificial_y_asistencia_de_moda.cu25_registrar_producto_asistido_por_ia import (
    _generar_ficha_estudio_fallback,
    ProductAiAssistExtendedRequest,
    ProductStudioAiContent,
)
from app.modules.carrito_pedidos_y_pagos.cu12_consultar_pedidos_e_historial_de_compras import download_receipt
from app.models.entities import Role


def test_seed_sample_balanced_products_by_category():
    # Simular filas de prueba con diferentes categorias y generos
    rows = [
        {"id": "1", "nombre": "Polera Basica", "descripcion": "Polera de algodon", "precio": "100", "genero": "MUJER"},
        {"id": "2", "nombre": "Camisa Oxford", "descripcion": "Camisa blanca", "precio": "150", "genero": "HOMBRE"},
        {"id": "3", "nombre": "Pantalon Chino", "descripcion": "Pantalon de lino", "precio": "200", "genero": "HOMBRE"},
        {"id": "4", "nombre": "Short Lino", "descripcion": "Short fresco", "precio": "120", "genero": "MUJER"},
        {"id": "5", "nombre": "Zapatos Oxford", "descripcion": "Calzado de cuero", "precio": "350", "genero": "HOMBRE"},
        {"id": "6", "nombre": "Botines Chelsea", "descripcion": "Botines de cuero", "precio": "380", "genero": "MUJER"},
        {"id": "7", "nombre": "Vestido Gala", "descripcion": "Vestido largo", "precio": "450", "genero": "MUJER"},
        {"id": "8", "nombre": "Abrigo Paño", "descripcion": "Abrigo lana", "precio": "500", "genero": "UNISEX"},
    ]

    sampled = sample_balanced_products(
        rows,
        tops_count=2,
        bottoms_count=2,
        shoes_count=1,
        dresses_count=1,
        outerwear_count=1,
    )
    assert len(sampled) == 7
    names = [r["nombre"] for r in sampled]
    assert "Polera Basica" in names or "Camisa Oxford" in names
    assert "Zapatos Oxford" in names or "Botines Chelsea" in names
    assert "Vestido Gala" in names
    assert "Abrigo Paño" in names


def test_cu26_reporte_resiliente():
    contexto_mock = {
        "periodo_analizado": "Mes en Curso (09/2026)",
        "indicadores_generales": {
            "ventas_totales_bob": 15420.50,
            "pedidos_totales": 28,
            "pedidos_entregados": 20,
            "pedidos_en_curso": 8,
            "ticket_promedio_bob": 550.73,
            "prendas_activas": 45,
            "variantes_totales": 180,
            "unidades_stock_disponible": 520,
            "variantes_stock_critico": 3,
            "sesiones_asistente_ia": 14,
            "interacciones_ia": 52,
            "latencia_promedio_ia_ms": 320,
        },
        "clientes_destacados": [
            {"nombre": "Carlos Rojas", "email": "carlos@example.com", "pedidos": 4, "facturado_bob": 3200.0}
        ],
        "articulos_vendidos": [
            {"prenda": "Abrigo Solapa Imperial", "categoria": "Abrigos", "unidades": 5, "subtotal_bob": 2250.0}
        ],
        "inventario_critico": [
            {"prenda": "Vestido Seda", "talla": "M", "color": "Negro", "stock_restante": 1}
        ],
        "desempeno_canales": [
            {"canal_sucursal": "Showroom Central", "ciudad": "Santa Cruz", "pedidos": 18, "total_bob": 10500.0}
        ],
    }

    reporte = _sintetizar_reporte_directivo_resiliente(contexto_mock, "Rendimiento y Stock")
    assert isinstance(reporte, ReporteDinamicoIA)
    assert "Auditoria" in reporte.titulo_reporte
    assert "DrapeMind Atelier" in reporte.tesis_central
    assert len(reporte.secciones) >= 4
    # Verificar tablas en secciones
    seccion_con_tablas = [s for s in reporte.secciones if len(s.tablas) > 0]
    assert len(seccion_con_tablas) >= 3
    assert reporte.indicadores_clave["ventas_totales_bob"] == 15420.50


def test_cu25_estudio_fallback():
    payload = ProductAiAssistExtendedRequest(
        nombre_borrador="Saco Cruzado en Alpaca",
        material="Alpaca Suri",
        estilo_objetivo="Sartorial Contemporáneo",
        genero_objetivo="HOMBRE",
        categoria_sugerida="Sacos",
    )
    fallback = _generar_ficha_estudio_fallback(payload, ["Sacos", "Pantalones", "Camisas"])
    assert isinstance(fallback, ProductStudioAiContent)
    assert "Saco Cruzado" in fallback.titulo_comercial
    assert fallback.categoria_recomendada == "Sacos"
    assert fallback.precio_sugerido_estimado >= Decimal("400.00")
    assert len(fallback.tags_estilo) >= 4
    assert "Alpaca" in fallback.descripcion_editorial


def test_cu12_receipt_json_allows_pending_order():
    db = MagicMock()
    order = SimpleNamespace(
        id=42,
        usuario_id=10,
        sucursal_id=1,
        estado="PENDIENTE_PAGO",
        codigo_publico="ORD-42-PEND",
        created_at=None,
        canal="DIGITAL",
        tipo_entrega="ENVIO_DOMICILIO",
        subtotal=Decimal("300.00"),
        descuento=Decimal("0.00"),
        costo_envio=Decimal("20.00"),
        total=Decimal("320.00"),
        observacion=None,
    )
    db.get.side_effect = lambda model, obj_id: order if obj_id == 42 else None
    db.scalars.return_value = []

    user = SimpleNamespace(id=10, rol=Role.CLIENTE)
    result = download_receipt(42, format="json", current_user=user, db=db)
    assert isinstance(result, dict)
    assert result["order"]["id"] == 42
    assert result["order"]["estado"] == "PENDIENTE_PAGO"

    # En cambio, si format != 'json' y no tiene pago aprobado, debe levantar 409
    with pytest.raises(HTTPException) as exc:
        download_receipt(42, format="text", current_user=user, db=db)
    assert exc.value.status_code == 409
