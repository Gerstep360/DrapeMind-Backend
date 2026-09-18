"""CU-26: Generar reportes empresariales mediante IA.
Paquete: Inteligencia artificial y asistencia de moda (PK-05).
"""
import re
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from typing import Any
from fastapi import APIRouter, Depends
from sqlalchemy import func, select, desc
from sqlalchemy.orm import Session

from app.api.deps import require_role
from app.db.session import get_db
from app.models import (
    AIInteraction,
    AISession,
    Branch,
    Category,
    City,
    Order,
    OrderItem,
    Payment,
    Product,
    ProductVariant,
    Role,
    User,
)
from app.schemas.api import ExecutiveReportRequest, ExecutiveReportResponse, ReportTable
from app.services.ai import call_gemma

router = APIRouter()


def _clean_ai_text(text: str) -> str:
    """Limpia encabezados redundantes, asteriscos sueltos y preámbulos de IA."""
    if not text:
        return ""
    # Eliminar títulos tipo "**INFORME ESTRATÉGICO...**" o encabezados iniciales
    text = re.sub(
        r"^\s*(\*\*|#+)?\s*(INFORME|ATELIER|TIPO DE INFORME|PERIODO|RESUMEN EJECUTIVO|DIAGNÓSTICO|DIAGNOSTICO)[\w\s\:\*]*(\*\*|\n)+",
        "",
        text,
        flags=re.IGNORECASE,
    )
    # Eliminar numeración inicial como "1. " o "2. "
    text = re.sub(r"^\s*\d+\.\s*", "", text)
    return text.strip()


@router.post(
    "/reports/executive-summary",
    summary="CU-26: Generar resumen ejecutivo inteligente de ventas y tendencias (Básico)",
    description="Analiza métricas de pedidos, prendas populares y genera un resumen gerencial en lenguaje natural.",
)
async def generar_resumen_ejecutivo_ia(
    _admin: User = Depends(require_role(Role.ADMIN)),
    db: Session = Depends(get_db),
) -> dict:
    """CU-26: Síntesis gerencial básica."""
    total_orders = db.scalar(select(func.count(Order.id))) or 0
    total_revenue = db.scalar(select(func.coalesce(func.sum(Order.total), Decimal("0.00")))) or Decimal("0.00")
    top_products = db.scalars(select(Product.nombre).where(Product.activo == True).limit(5)).all()

    data_summary = f"Total Pedidos: {total_orders}, Ingresos Totales: Bs {total_revenue:.2f}, Top Prendas: {', '.join(top_products)}"
    prompt = (
        f"Analiza los siguientes indicadores del negocio de moda y redacta un informe ejecutivo con 3 oportunidades de crecimiento: {data_summary}. "
        "REGLA CRÍTICA: CERO EMOJIS."
    )

    summary = ""
    try:
        res, _ = await call_gemma("Eres un consultor de negocios y analista estratégico de retail de lujo. CERO EMOJIS.", prompt)
        summary = _clean_ai_text(res) if res else ""
    except Exception:
        summary = ""

    if not summary:
        summary = (
            f"El atelier registra un volumen acumulado de {total_orders} pedidos con una facturación global de "
            f"Bs {total_revenue:.2f}. Se observa una alta concentración de interés en la línea de {top_products[0] if top_products else 'prendas sastreras'}, "
            "lo cual sugiere consolidar la reposición de tallas clave y optimizar las campañas de fidelización."
        )

    return {
        "indicadores_base": {
            "total_pedidos": total_orders,
            "ingresos_totales_bob": float(total_revenue),
            "prendas_analizadas": len(top_products),
        },
        "informe_ejecutivo": summary,
    }


@router.post(
    "/reports/generate",
    response_model=ExecutiveReportResponse,
    summary="CU-26: Generar informe empresarial estructurado con IA",
    description="Genera un diagnóstico integral de ventas, inventario, comportamiento de clientes y recomendaciones estratégicas.",
)
async def generar_informe_empresarial_ia(
    payload: ExecutiveReportRequest,
    _admin: User = Depends(require_role(Role.ADMIN)),
    db: Session = Depends(get_db),
) -> ExecutiveReportResponse:
    """CU-26: Motor de generación de reportes estratégicos multitemáticos."""
    now = datetime.now(timezone.utc)
    start_date = None
    periodo_humano = "Histórico Completo"

    if payload.periodo == "MES_ACTUAL":
        start_date = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        periodo_humano = f"Mes en Curso ({now.strftime('%m/%Y')})"
    elif payload.periodo == "TRIMESTRE":
        start_date = now - timedelta(days=90)
        periodo_humano = "Último Trimestre Operativo (90 días)"

    # 1. Filtros temporales precisos
    order_filter = []
    payment_filter = [Payment.estado == "APROBADO"]
    ai_filter = []
    if start_date:
        order_filter.append(Order.created_at >= start_date)
        payment_filter.append(Payment.created_at >= start_date)
        ai_filter.append(AIInteraction.created_at >= start_date)

    # 2. Recolección de métricas cuantitativas
    total_orders = db.scalar(select(func.count(Order.id)).where(*order_filter)) or 0
    delivered_orders = db.scalar(
        select(func.count(Order.id)).where(Order.estado == "ENTREGADO", *order_filter)
    ) or 0
    pending_orders = db.scalar(
        select(func.count(Order.id)).where(
            Order.estado.in_(["PENDIENTE_PAGO", "PAGADO", "PREPARANDO", "LISTO", "ENVIADO"]),
            *order_filter,
        )
    ) or 0

    total_revenue = db.scalar(select(func.coalesce(func.sum(Payment.monto), Decimal("0.00"))).where(*payment_filter)) or Decimal("0.00")
    if total_revenue == Decimal("0.00"):
        total_revenue = db.scalar(
            select(func.coalesce(func.sum(Order.total), Decimal("0.00"))).where(
                Order.estado.in_(["COMPLETADO", "CONFIRMADO", "ENTREGADO", "PAGADO"]),
                *order_filter,
            )
        ) or Decimal("0.00")

    # Si en el mes actual no hay órdenes aún, recopilar también el acumulado histórico para contextualizar
    historical_orders = db.scalar(select(func.count(Order.id))) or 0
    historical_revenue = db.scalar(select(func.coalesce(func.sum(Payment.monto), Decimal("0.00"))).where(Payment.estado == "APROBADO")) or Decimal("0.00")

    ticket_promedio = (total_revenue / total_orders) if total_orders > 0 else (
        (historical_revenue / historical_orders) if historical_orders > 0 else Decimal("0.00")
    )

    total_products = db.scalar(select(func.count(Product.id)).where(Product.activo == True)) or 0
    total_variants = db.scalar(select(func.count(ProductVariant.id)).where(ProductVariant.activo == True)) or 0
    stock_total_units = db.scalar(
        select(func.coalesce(func.sum(ProductVariant.stock_total - ProductVariant.stock_reservado), 0)).where(ProductVariant.activo == True)
    ) or 0
    low_stock_variants = db.scalar(
        select(func.count(ProductVariant.id)).where(
            ProductVariant.activo == True,
            (ProductVariant.stock_total - ProductVariant.stock_reservado) <= 3,
        )
    ) or 0

    total_ai_sessions = db.scalar(select(func.count(AISession.id))) or 0
    total_ai_interactions = db.scalar(select(func.count(AIInteraction.id)).where(*ai_filter)) or 0
    avg_ai_duration = db.scalar(select(func.coalesce(func.avg(AIInteraction.duracion_ms), 0.0)).where(*ai_filter)) or 0.0

    indicadores = {
        "ventas_totales_bob": float(total_revenue),
        "pedidos_totales": total_orders,
        "pedidos_entregados": delivered_orders,
        "pedidos_en_curso": pending_orders,
        "ticket_promedio_bob": round(float(ticket_promedio), 2),
        "prendas_activas": total_products,
        "variantes_totales": total_variants,
        "unidades_stock_disponible": stock_total_units,
        "variantes_stock_critico": low_stock_variants,
        "sesiones_asistente_ia": total_ai_sessions,
        "interacciones_ia": total_ai_interactions,
        "latencia_promedio_ia_ms": round(float(avg_ai_duration), 2),
        "periodo_auditado": periodo_humano,
    }

    # 3. Consultas Analíticas Específicas para Tablas y Enfoque Directivo
    # A) Top Clientes por Facturación (auditoría de clientes clave)
    completed_filter = [Order.estado.in_(["COMPLETADO", "CONFIRMADO", "ENTREGADO", "PAGADO", "LISTO"])]
    top_users_query = (
        select(
            User.nombre,
            User.email,
            func.count(Order.id).label("total_pedidos"),
            func.coalesce(func.sum(Order.total), Decimal("0.00")).label("total_gastado"),
        )
        .join(Order, Order.usuario_id == User.id)
        .where(*completed_filter)
        .group_by(User.id)
        .order_by(desc("total_gastado"))
        .limit(5)
    )
    top_users = db.execute(top_users_query).all()

    # Si no hay completados, obtener los usuarios con cualquier pedido registrado
    if not top_users:
        fallback_users_query = (
            select(
                User.nombre,
                User.email,
                func.count(Order.id).label("total_pedidos"),
                func.coalesce(func.sum(Order.total), Decimal("0.00")).label("total_gastado"),
            )
            .join(Order, Order.usuario_id == User.id)
            .group_by(User.id)
            .order_by(desc("total_gastado"))
            .limit(5)
        )
        top_users = db.execute(fallback_users_query).all()

    # B) Top Prendas Más Vendidas
    top_products_query = (
        select(
            OrderItem.nombre_snapshot,
            func.coalesce(Category.nombre, "Línea Atelier").label("categoria"),
            func.sum(OrderItem.cantidad).label("unidades_vendidas"),
            func.coalesce(func.sum(OrderItem.subtotal), Decimal("0.00")).label("total_facturado"),
        )
        .join(Order, Order.id == OrderItem.pedido_id)
        .outerjoin(Product, Product.id == OrderItem.producto_id)
        .outerjoin(Category, Category.id == Product.categoria_id)
        .group_by(OrderItem.nombre_snapshot, Category.nombre)
        .order_by(desc("unidades_vendidas"))
        .limit(5)
    )
    top_products_data = db.execute(top_products_query).all()

    # C) Variantes con Stock Crítico
    critical_stock_query = (
        select(
            Product.nombre,
            ProductVariant.talla,
            ProductVariant.color,
            (ProductVariant.stock_total - ProductVariant.stock_reservado).label("disponible"),
            func.coalesce(Category.nombre, "Atelier").label("categoria"),
        )
        .join(Product, Product.id == ProductVariant.producto_id)
        .outerjoin(Category, Category.id == Product.categoria_id)
        .where(
            ProductVariant.activo.is_(True),
            (ProductVariant.stock_total - ProductVariant.stock_reservado) <= 3,
        )
        .order_by((ProductVariant.stock_total - ProductVariant.stock_reservado).asc())
        .limit(5)
    )
    critical_stock_data = db.execute(critical_stock_query).all()

    # D) Desempeño por Canal y Sedes Físicas
    branch_sales_query = (
        select(
            func.coalesce(Branch.nombre, "Canal Digital / Online").label("sede"),
            func.coalesce(City.nombre, "Nacional").label("ciudad"),
            func.count(Order.id).label("total_pedidos"),
            func.coalesce(func.sum(Order.total), Decimal("0.00")).label("facturado"),
        )
        .outerjoin(Branch, Branch.id == Order.sucursal_id)
        .outerjoin(City, City.id == Branch.ciudad_id)
        .group_by(Branch.nombre, City.nombre)
        .order_by(desc("facturado"))
        .limit(5)
    )
    branch_sales_data = db.execute(branch_sales_query).all()

    # 4. Generación de Tablas Analíticas Estructuradas
    tablas_analiticas: list[ReportTable] = []

    # Tabla 1: Clientes Líderes
    if top_users:
        filas_usuarios = []
        for idx, u in enumerate(top_users):
            monto = float(u.total_gastado)
            segmento = "VIP Atelier" if monto >= 1500 or u.total_pedidos >= 3 else "Frecuente"
            filas_usuarios.append([
                u.nombre or f"Cliente #{idx+1}",
                u.email or "Sin correo",
                f"{u.total_pedidos} orden{'es' if u.total_pedidos != 1 else ''}",
                f"Bs {monto:,.2f}",
                segmento,
            ])
        cliente_top_nombre = top_users[0].nombre or "Cliente Principal"
        cliente_top_monto = float(top_users[0].total_gastado)
        tablas_analiticas.append(
            ReportTable(
                titulo="Clientes con Mayor Volumen de Compra y Facturación",
                columnas=["Cliente", "Correo de Contacto", "Pedidos Realizados", "Inversión Total", "Segmento"],
                filas=filas_usuarios,
                resumen=f"El cliente con mayor volumen de compra es {cliente_top_nombre} con una inversión total de Bs {cliente_top_monto:,.2f}.",
            )
        )

    # Tabla 2: Catálogo y Demanda de Prendas
    if top_products_data:
        filas_prendas = []
        for p in top_products_data:
            monto = float(p.total_facturado)
            rotacion = "Alta Rotación" if p.unidades_vendidas >= 4 else "Demanda Moderada"
            filas_prendas.append([
                p.nombre_snapshot or "Prenda Sastrera",
                p.categoria or "Línea General",
                f"{p.unidades_vendidas} uds",
                f"Bs {monto:,.2f}",
                rotacion,
            ])
        tablas_analiticas.append(
            ReportTable(
                titulo="Prendas Sastreras con Mayor Demanda y Rotación Comercial",
                columnas=["Prenda / Modelo", "Colección", "Unidades Vendidas", "Facturación Bruta", "Rotación"],
                filas=filas_prendas,
                resumen=f"La prenda líder en ventas es '{top_products_data[0].nombre_snapshot}' con {top_products_data[0].unidades_vendidas} unidades desplazadas.",
            )
        )

    # Tabla 3: Estado de Inventario Crítico
    if critical_stock_data:
        filas_stock = []
        for s in critical_stock_data:
            prioridad = "CRÍTICA (URGENTE)" if s.disponible <= 1 else "Reposición Regular"
            filas_stock.append([
                s.nombre,
                s.categoria,
                str(s.talla),
                str(s.color),
                f"{s.disponible} uds",
                prioridad,
            ])
        tablas_analiticas.append(
            ReportTable(
                titulo="Inventario en Umbral de Stock Crítico (<= 3 Unidades)",
                columnas=["Prenda", "Línea", "Talla", "Color", "Stock Disponible", "Prioridad Taller"],
                filas=filas_stock,
                resumen=f"Se identifican {len(critical_stock_data)} variantes prioritarias para reposición inmediata con proveedores de tela.",
            )
        )

    # Tabla 4: Ventas por Canal y Sucursal
    if branch_sales_data and any(b.total_pedidos > 0 for b in branch_sales_data):
        filas_canales = [
            [
                b.sede,
                b.ciudad,
                f"{b.total_pedidos} pedidos",
                f"Bs {float(b.facturado):,.2f}",
            ]
            for b in branch_sales_data
        ]
        tablas_analiticas.append(
            ReportTable(
                titulo="Distribución de Facturación por Sedes y Canales",
                columnas=["Canal / Sucursal", "Ciudad", "Pedidos", "Facturación Neta"],
                filas=filas_canales,
                resumen=f"Canal principal: {branch_sales_data[0].sede} con Bs {float(branch_sales_data[0].facturado):,.2f}.",
            )
        )

    # 5. Tratamiento Específico del Enfoque del Directorio
    enfoque_analisis_texto = None
    if payload.enfoque_especifico and payload.enfoque_especifico.strip():
        enfoque_raw = payload.enfoque_especifico.strip()
        enfoque_lower = enfoque_raw.lower()

        if any(w in enfoque_lower for w in ["cliente", "compra", "quien", "comprador", "usuario", "gasto", "factura"]):
            if top_users:
                top_u = top_users[0]
                monto = float(top_u.total_gastado)
                sec_txt = ""
                if len(top_users) > 1:
                    u2 = top_users[1]
                    sec_txt = f" En segunda posición se ubica **{u2.nombre}** con una facturación acumulada de **Bs {float(u2.total_gastado):,.2f}** ({u2.total_pedidos} pedidos)."
                enfoque_analisis_texto = (
                    f"Respecto a su enfoque de análisis ('{enfoque_raw}'): "
                    f"El cliente con mayor volumen de compra en la plataforma es **{top_u.nombre}** ({top_u.email}), "
                    f"quien acumula un total de **Bs {monto:,.2f}** en **{top_u.total_pedidos} pedidos**.{sec_txt} "
                    f"Se recomienda habilitar para este segmento directrices de fidelización sastrera personalizada, reserva anticipada de colecciones y bonificaciones directas."
                )
            else:
                enfoque_analisis_texto = (
                    f"Respecto a su enfoque de análisis ('{enfoque_raw}'): "
                    "El historial transaccional se encuentra en etapa de sincronización operativa. "
                    "Se recomienda consolidar los pedidos en curso para perfilar el ticket de compra por cliente."
                )
        elif any(w in enfoque_lower for w in ["prenda", "producto", "mas vendid", "rotacion", "demanda", "articulo"]):
            if top_products_data:
                tp = top_products_data[0]
                enfoque_analisis_texto = (
                    f"Respecto a su enfoque de análisis ('{enfoque_raw}'): "
                    f"La prenda sastrera con mayor volumen de ventas es **{tp.nombre_snapshot}** ({tp.categoria}), "
                    f"con **{tp.unidades_vendidas} unidades comercializadas** y una recaudación bruta de **Bs {float(tp.total_facturado):,.2f}**. "
                    "Se sugiere priorizar la compra de tejidos con hilanderías aliadas para mantener el ritmo de reposición."
                )
            else:
                enfoque_analisis_texto = (
                    f"Respecto a su enfoque de análisis ('{enfoque_raw}'): "
                    f"El catálogo activo cuenta con {total_products} prendas activas y {stock_total_units} unidades en inventario físico."
                )
        elif any(w in enfoque_lower for w in ["stock", "inventario", "escasez", "almacen", "talla"]):
            enfoque_analisis_texto = (
                f"Respecto a su enfoque de análisis ('{enfoque_raw}'): "
                f"Actualmente existen **{low_stock_variants} variantes en umbral crítico** (menor o igual a 3 unidades). "
                f"El stock total disponible suma {stock_total_units} prendas distribuidas en el catálogo. "
                "La alerta de reabastecimiento debe concentrarse prioritariamente en cortes de alta demanda sastrera."
            )
        else:
            enfoque_analisis_texto = (
                f"Respecto a su enfoque de análisis ('{enfoque_raw}'): "
                f"Cruzando los datos del periodo ({periodo_humano}), DrapeMind registra {total_orders} pedidos "
                f"con una facturación de Bs {total_revenue:,.2f}. La convergencia de los {total_ai_sessions} procesos de asistencia IA "
                f"respalda una estrategia centrada en {enfoque_raw} para optimizar el margen y la satisfacción del cliente."
            )

    # 6. Elaboración de Textos Ejecutivos según el Motor de IA Seleccionado
    modelo_seleccionado = payload.modelo_ia or "ALTAIR"
    if modelo_seleccionado == "ALTAIR_MINI":
        nombre_modelo = "Altair Mini (Scout 0.6B - Inferencia Rápida)"
        system_prompt = (
            "Eres Altair Mini, motor de analítica ágil y velocidad operativa de DrapeMind. "
            "REGLAS OBLIGATORIAS: CERO EMOJIS. Respuestas ultraconcisas, cuantitativas, viñetas directas sin rodeos. Moneda: Bolivianos (Bs)."
        )
        executive_body = (
            f"• Facturación y Órdenes: Bs {total_revenue:,.2f} consolidados en {total_orders} pedidos (Ticket medio: Bs {ticket_promedio:,.2f}).\n"
            f"• Eficiencia de Despacho: {delivered_orders} entregas efectivas ({((delivered_orders / total_orders * 100) if total_orders else 100):.1f}%), {pending_orders} pedidos activos en taller/tránsito.\n"
            f"• Disponibilidad de Piso: {stock_total_units} prendas en almacén con {low_stock_variants} variantes en umbral crítico (<= 3 unidades)."
        )
        diagnostic_body = (
            f"• Acción 24h-48h: Emitir orden de reposición inmediata a hilanderías para las {low_stock_variants} variantes bajo umbral mínimo.\n"
            f"• Rendimiento IA: Asistente operando con latencia media de {avg_ai_duration:.1f} ms en {total_ai_interactions} consultas asistidas.\n"
            f"• Optimización Táctica: Priorizar la liberación de los {pending_orders} pedidos en preparación para acelerar el flujo de caja."
        )
    elif modelo_seleccionado == "ALTAIR_VARIABLE":
        nombre_modelo = "Altair Variable (Orquestación Híbrida Dinámica)"
        system_prompt = (
            "Eres Altair Variable, motor adaptativo de inteligencia retail y sastería inteligente. "
            "REGLAS OBLIGATORIAS: CERO EMOJIS. Estilo dinámico con balance entre rapidez operativa de piso y visión estratégica comercial. Moneda: Bolivianos (Bs)."
        )
        executive_body = (
            f"Diagnóstico Adaptativo DrapeMind: El modelo detecta una facturación consolidada de Bs {total_revenue:,.2f} en {total_orders} órdenes, "
            f"con un ticket promedio de Bs {ticket_promedio:,.2f}. La red física y digital mantiene {stock_total_units} prendas activas en {total_products} modelos. "
            f"La orquestación dinámica prioriza simultáneamente la reposición de las {low_stock_variants} variantes en umbral crítico y el fortalecimiento del estilismo asistido."
        )
        diagnostic_body = (
            f"Equilibrio Táctico-Estratégico: En el eje de piso de venta, {delivered_orders} entregas han sido completadas satisfactoriamente mientras que {pending_orders} pedidos continúan en preparación. "
            f"En el eje estratégico, la latencia media de asistencia ({avg_ai_duration:.1f} ms en {total_ai_sessions} sesiones) respalda la expansión del catálogo con proveedores textiles aliados."
        )
    else:  # ALTAIR
        nombre_modelo = "Altair Principal (Gemma 4 E2B - Razonamiento Profundo)"
        system_prompt = (
            "Eres Altair Principal, Consultor Estratégico Senior de Retail de Lujo y Alta Costura de DrapeMind Atelier. "
            "REGLAS OBLIGATORIAS: CERO EMOJIS. Lenguaje directivo de alto impacto, cuantitativo, elegante y riguroso. Moneda: Bolivianos (Bs)."
        )
        if payload.tipo_reporte == "VENTAS_Y_TENDENCIAS":
            executive_body = (
                f"Durante el periodo correspondiente a {periodo_humano.lower()}, DrapeMind consolidó ingresos por "
                f"Bs {total_revenue:,.2f} a través de {total_orders} órdenes registradas, alcanzando un ticket promedio de Bs {ticket_promedio:,.2f}. "
                f"El ratio de cumplimiento comercial se refleja en {delivered_orders} pedidos entregados satisfactoriamente, "
                f"mientras que {pending_orders} pedidos avanzan en fase de preparación y distribución sastrera."
            )
            diagnostic_body = (
                f"El análisis de tendencia de ventas muestra un comportamiento robusto en las prendas sastreras insignia. "
                f"El {((delivered_orders / total_orders * 100) if total_orders else 100):.1f}% de las órdenes auditadas han completado el ciclo de entrega. "
                f"Los clientes de mayor frecuencia concentran el volumen principal de ingresos, lo que demuestra la efectividad de la propuesta de alta costura."
            )
        elif payload.tipo_reporte == "INVENTARIO_Y_STOCK":
            executive_body = (
                f"La auditoría de existencias al cierre del periodo ({periodo_humano.lower()}) comprende {total_products} modelos activos "
                f"con un total de {stock_total_units} unidades físicas en almacenes. Se identifican {low_stock_variants} variantes en umbral crítico "
                f"de reposición (menor o igual a 3 unidades), requiriendo órdenes de compra programadas a proveedores de lino, seda y alpaca."
            )
            diagnostic_body = (
                f"El índice de stock crítico representa el {((low_stock_variants / total_variants * 100) if total_variants else 0):.1f}% de las variantes activas. "
                "La rotación es balanceada en la colección principal, pero se aconseja regularizar el reabastecimiento en tallas centrales "
                "para evitar pérdidas por demanda insatisfecha en probadores virtuales."
            )
        elif payload.tipo_reporte == "ASISTENCIA_IA_Y_CLIENTES":
            executive_body = (
                f"El motor de estilismo Altair registró {total_ai_sessions} sesiones y {total_ai_interactions} interacciones asistidas "
                f"en el periodo ({periodo_humano.lower()}), con una latencia media de respuesta de {avg_ai_duration:.1f} ms. "
                "La interacción automatizada ha elevado la retención de clientes en catálogo, guiando compras informadas en base al ADN de estilo."
            )
            diagnostic_body = (
                f"La latencia operativa promedio de {avg_ai_duration:.1f} ms cumple holgadamente los estándares de servicio directivo (< 3,000 ms). "
                f"La asistencia inteligente ha demostrado correlación directa con la adición de prendas al perchero virtual, "
                f"reduciendo la tasa de dudas en selección de tallas y cortes sastreros."
            )
        else:  # ESTRATEGICO_GLOBAL
            executive_body = (
                f"El diagnóstico directivo global de DrapeMind sintetiza una facturación consolidada de Bs {total_revenue:,.2f} "
                f"distribuida en {total_orders} pedidos, respaldada por un catálogo de {total_products} prendas activas ({stock_total_units} unidades en red). "
                f"La sincronización entre el probador virtual, la IA Altair y los talleres sastreros posiciona favorablemente a la marca para su expansión."
            )
            diagnostic_body = (
                f"La salud financiera y operativa del atelier presenta estabilidad general. "
                f"Se combinan {delivered_orders} entregas completadas, un ticket medio de Bs {ticket_promedio:,.2f} y una base de fidelización en crecimiento. "
                f"La gestión de las {low_stock_variants} variantes bajo umbral y la potenciación del motor de estilismo son los dos pilares estratégicos de escala."
            )

    # 7. Si Gemma está disponible, enriquecer la redacción con el estilo del modelo elegido
    try:
        data_context = (
            f"Datos Reales del Atelier DrapeMind:\n"
            f"- Tipo de Reporte: {payload.tipo_reporte}\n"
            f"- Periodo: {periodo_humano}\n"
            f"- Motor IA: {nombre_modelo}\n"
            f"- Facturación Auditada: Bs {total_revenue:,.2f}\n"
            f"- Pedidos Totales: {total_orders} (Entregados: {delivered_orders}, En Curso: {pending_orders})\n"
            f"- Ticket Promedio: Bs {ticket_promedio:,.2f}\n"
            f"- Catálogo: {total_products} prendas ({total_variants} variantes, {stock_total_units} unidades en inventario)\n"
            f"- Variantes en Riesgo de Stock: {low_stock_variants}\n"
            f"- Asistente IA: {total_ai_sessions} sesiones, {total_ai_interactions} consultas (latencia: {avg_ai_duration:.1f} ms)\n"
            f"- Enfoque del Directorio: {payload.enfoque_especifico or 'Crecimiento sostenible y satisfacción sastrera'}\n"
        )
        if modelo_seleccionado == "ALTAIR_MINI":
            estilo_instruccion = (
                "Formato requerido: Genera 3 viñetas cuantitativas y ultrarrápidas para el Resumen Ejecutivo, "
                "y 3 acciones tácticas directas (24h/48h) para el Diagnóstico."
            )
        elif modelo_seleccionado == "ALTAIR_VARIABLE":
            estilo_instruccion = (
                "Formato requerido: Articula un diagnóstico dinámico y balanceado que integre las alertas operativas "
                "inmediatas de inventario con las directrices de crecimiento comercial."
            )
        else:
            estilo_instruccion = (
                "Formato requerido: Redacta un informe estratégico de alto nivel directivo (McKinsey / Bain), "
                "con prosa formal, visión financiera y posicionamiento de marca de lujo."
            )

        prompt = (
            f"Genera un informe estratégico formal para el directorio de DrapeMind con los siguientes datos:\n{data_context}\n"
            f"{estilo_instruccion}\n"
            "REGLAS OBLIGATORIAS:\n"
            "1. CERO EMOJIS.\n"
            "2. No agregues preámbulos, títulos generales ni frases como 'INFORME ESTRATÉGICO', 'Atelier DrapeMind', 'Tipo de informe', 'Periodo' o '1. RESUMEN EJECUTIVO'.\n"
            "3. Empieza directamente con la síntesis del texto.\n"
            "4. Separa las dos secciones exactamente con la palabra: [SECCION_DIAGNOSTICO].\n"
        )
        raw_res, _ = await call_gemma(system_prompt, prompt)
        if raw_res and len(raw_res) > 80:
            parts = raw_res.split("[SECCION_DIAGNOSTICO]")
            cleaned_exec = _clean_ai_text(parts[0])
            if len(cleaned_exec) > 60:
                executive_body = cleaned_exec
            if len(parts) > 1:
                cleaned_diag = _clean_ai_text(parts[1])
                if len(cleaned_diag) > 60:
                    diagnostic_body = cleaned_diag
    except Exception:
        pass

    # 8. Cuellos de Botella Dinámicos
    bottlenecks: list[str] = []
    if low_stock_variants > 0:
        bottlenecks.append(f"Riesgo de desabastecimiento en {low_stock_variants} variantes de alta rotación con stock menor o igual a 3 unidades.")
    else:
        bottlenecks.append("Estabilidad de existencias en catálogo; mantener control en rotación de temporadas.")

    if pending_orders > 0:
        bottlenecks.append(f"Tiempo de ciclo de preparación: {pending_orders} pedidos en tránsito, almacén o pendientes de pago.")
    else:
        bottlenecks.append("Flujo de pedidos 100% al día sin acumulaciones de pedidos en espera.")

    if total_ai_interactions > 0 and avg_ai_duration > 2500:
        bottlenecks.append(f"Latencia media de IA en {avg_ai_duration:.1f} ms; considerar optimización de caché para consultas repetidas.")
    else:
        bottlenecks.append("Oportunidad de maximizar la conversión de clientes desde el probador virtual hacia la pasarela de compra.")

    # 9. Recomendaciones Estratégicas Dinámicas
    recommendations: list[str] = []
    if top_users:
        recommendations.append(f"Activar programa de fidelización y trato exclusivo para los clientes líderes en facturación ({top_users[0].nombre}).")
    else:
        recommendations.append("Implementar campañas de captación de clientes VIP en canales digitales y redes sociales.")

    if low_stock_variants > 0:
        recommendations.append("Emitir órdenes de suministro a hilanderías aliadas para reponer las variantes con stock crítico.")
    else:
        recommendations.append("Programar lanzamiento de nuevas colecciones de temporada aprovechando la solidez de inventario.")

    recommendations.append(
        f"Promocionar prendas sastreras con mayor volumen disponible ({stock_total_units} unidades en red) mediante recomendaciones del asistente Altair."
    )

    return ExecutiveReportResponse(
        tipo_reporte=payload.tipo_reporte,
        periodo=payload.periodo,
        modelo_utilizado=nombre_modelo,
        indicadores_clave=indicadores,
        resumen_ejecutivo=executive_body,
        diagnostico_rendimiento=diagnostic_body,
        enfoque_personalizado=enfoque_analisis_texto,
        tablas_analiticas=tablas_analiticas,
        cuellos_de_botella=bottlenecks,
        recomendaciones_estrategicas=recommendations,
        fecha_generacion=datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M UTC"),
    )
