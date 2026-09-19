"""CU-26: Generar reportes empresariales mediante IA con estructura totalmente libre y dinámica.
Paquete: Inteligencia artificial y asistencia de moda (PK-05).
"""
import json
import re
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
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
from app.schemas.api import (
    ExecutiveReportRequest,
    ExecutiveReportResponse,
    ReporteDinamicoIA,
    SeccionDinamica,
    TablaDinamica,
)
from app.services.ai import call_gemma
from app.services.push_notifications import dispatch_notification

router = APIRouter()


def _extract_json_payload(text: str) -> dict:
    """Extrae un payload JSON válido limpiando delimitadores de bloques de código."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        first_newline = cleaned.find("\n")
        if first_newline != -1:
            cleaned = cleaned[first_newline + 1:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        cleaned = cleaned.strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if match:
            return json.loads(match.group(0))
        raise


# -----------------------------------------------------------------
# 1. Motor de IA con Libertad Estructural Absoluta (Sin Plantillas)
# -----------------------------------------------------------------
async def generar_reporte_totalmente_libre(
    contexto_datos: dict,
    enfoque: str | None,
    modelo_ia: str | None = None,
    seed: int | None = None,
) -> ReporteDinamicoIA:
    """La IA decide títulos, secciones, narrativa y tablas analíticas según los datos reales."""
    system_prompt = (
        "Eres un auditor y consultor directivo senior de alta costura y retail de lujo. "
        "Tu labor es auditar los datos y armar un informe a tu propio criterio profesional. "
        "No uses plantillas genéricas, ni títulos repetitivos de manual (prohibido usar 'Resumen Ejecutivo', "
        "'Diagnóstico', 'Cuellos de Botella' o listas numeradas rígidas). "
        "Determina los títulos, la cantidad de secciones, la narrativa y si necesitas apoyar tus argumentos con "
        "tablas o no. Formato exclusivo: JSON válido. CERO EMOJIS."
    )

    user_prompt = f"""
Datos reales extraídos de la base de datos:
{json.dumps(contexto_datos, indent=2, default=str, ensure_ascii=False)}

Petición del usuario / Enfoque directivo:
{enfoque or "Auditoría general del estado del negocio, rentabilidad y operaciones"}

INSTRUCCIONES DE GENERACIÓN:
1. Diseña la estructura del reporte como mejor consideres para comunicar la situación real.
2. Define títulos descriptivos que reflejen el hallazgo de cada bloque (por ejemplo: 'Concentración de ingresos en alta costura masculina', 'Descalce de inventario en cortes de lino', etc.).
3. Genera tablas cuantitativas ÚNICAMENTE en las secciones donde una tabla aporte valor para entender las cifras. Define tú las columnas y filas usando los datos provistos. Si una sección se explica mejor con prosa, no incluyas tablas en ella.
4. Genera entre 2 y 5 secciones según la complejidad de los datos.
5. Moneda en Bolivianos (Bs).

ESTRUCTURA JSON EXACTA REQUERIDA:
{{
  "titulo_reporte": "Título principal contextualizado al informe",
  "tesis_central": "Conclusión o hallazgo principal en uno o dos párrafos",
  "secciones": [
    {{
      "titulo": "Título analítico original inventado según los hallazgos",
      "contenido": "Desarrollo analítico y cuantitativo de la sección",
      "tablas": [
        {{
          "titulo": "Título descriptivo asignado a la tabla",
          "columnas": ["Columna A", "Columna B"],
          "filas": [["Dato 1", "Dato 2"]],
          "nota_al_pie": "Conclusión puntual o aclaratoria de la tabla (opcional)"
        }}
      ]
    }}
  ]
}}

REGLAS OBLIGATORIAS:
- Responde EXCLUSIVAMENTE con el objeto JSON válido. Cero preámbulos o comentarios fuera del JSON.
- CERO EMOJIS.
"""

    try:
        raw_response, _ = await call_gemma(
            system=system_prompt,
            user=user_prompt,
            response_format={"type": "json_object"},
            seed=seed,
            temperature=0.35,
            max_tokens=1500,
        )
        data = _extract_json_payload(raw_response)
        return ReporteDinamicoIA.model_validate(data)
    except Exception as e:
        raise HTTPException(
            status_code=502,
            detail=f"Error en el motor de inferencia de IA al procesar el reporte: {str(e)}",
        )


# -----------------------------------------------------------------
# 2. Extracción de Métricas Puras de Base de Datos (SQLAlchemy)
# -----------------------------------------------------------------
def recopilar_metricas_bd(db: Session, periodo: str):
    """Extrae exclusivamente los datos duros cuantitativos de la base de datos."""
    now = datetime.now(timezone.utc)
    start_date = None
    periodo_humano = "Histórico Completo"

    if periodo == "MES_ACTUAL":
        start_date = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        periodo_humano = f"Mes en Curso ({now.strftime('%m/%Y')})"
    elif periodo == "TRIMESTRE":
        start_date = now - timedelta(days=90)
        periodo_humano = "Último Trimestre Operativo (90 días)"

    # Filtros temporales
    order_filter = []
    payment_filter = [Payment.estado == "APROBADO"]
    ai_filter = []
    if start_date:
        order_filter.append(Order.created_at >= start_date)
        payment_filter.append(Payment.created_at >= start_date)
        ai_filter.append(AIInteraction.created_at >= start_date)

    # Métricas agregadas de pedidos e ingresos
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

    total_revenue = db.scalar(
        select(func.coalesce(func.sum(Payment.monto), Decimal("0.00"))).where(*payment_filter)
    ) or Decimal("0.00")

    if total_revenue == Decimal("0.00"):
        total_revenue = db.scalar(
            select(func.coalesce(func.sum(Order.total), Decimal("0.00"))).where(
                Order.estado.in_(["ENTREGADO", "PAGADO", "LISTO", "ENVIADO"]),
                *order_filter,
            )
        ) or Decimal("0.00")

    historical_orders = db.scalar(select(func.count(Order.id))) or 0
    historical_revenue = db.scalar(
        select(func.coalesce(func.sum(Payment.monto), Decimal("0.00"))).where(Payment.estado == "APROBADO")
    ) or Decimal("0.00")

    ticket_promedio = (
        (total_revenue / total_orders)
        if total_orders > 0
        else ((historical_revenue / historical_orders) if historical_orders > 0 else Decimal("0.00"))
    )

    # Métricas de catálogo e inventario
    total_products = db.scalar(select(func.count(Product.id)).where(Product.activo == True)) or 0
    total_variants = db.scalar(select(func.count(ProductVariant.id)).where(ProductVariant.activo == True)) or 0
    stock_total_units = db.scalar(
        select(func.coalesce(func.sum(ProductVariant.stock_total - ProductVariant.stock_reservado), 0)).where(
            ProductVariant.activo == True
        )
    ) or 0
    low_stock_variants = db.scalar(
        select(func.count(ProductVariant.id)).where(
            ProductVariant.activo == True,
            (ProductVariant.stock_total - ProductVariant.stock_reservado) <= 3,
        )
    ) or 0

    # Métricas de asistencia IA
    total_ai_sessions = db.scalar(select(func.count(AISession.id))) or 0
    total_ai_interactions = db.scalar(select(func.count(AIInteraction.id)).where(*ai_filter)) or 0
    avg_ai_duration = db.scalar(
        select(func.coalesce(func.avg(AIInteraction.duracion_ms), 0.0)).where(*ai_filter)
    ) or 0.0

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

    # Clientes con mayor volumen
    completed_filter = [Order.estado.in_(["ENTREGADO", "PAGADO", "LISTO", "ENVIADO"])]
    if start_date:
        completed_filter.append(Order.created_at >= start_date)
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
        .limit(6)
    )
    top_users = db.execute(top_users_query).all()
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
            .limit(6)
        )
        top_users = db.execute(fallback_users_query).all()

    # Artículos más demandados
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
        .limit(6)
    )
    top_products = db.execute(top_products_query).all()

    # Variantes con stock crítico
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
        .limit(6)
    )
    critical_stock = db.execute(critical_stock_query).all()

    # Rendimiento por sedes y canales
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
        .limit(6)
    )
    branch_sales = db.execute(branch_sales_query).all()

    return indicadores, top_users, top_products, critical_stock, branch_sales, periodo_humano


# -----------------------------------------------------------------
# 3. Endpoint Principal CU-26 con Estructura Dinámica y Libre
# -----------------------------------------------------------------
@router.post(
    "/reports/generate",
    response_model=ReporteDinamicoIA,
    summary="CU-26: Generar informe empresarial estructurado por IA",
    description="La IA diseña libremente títulos, secciones, narrativa y tablas analíticas según los datos reales.",
)
async def generar_informe_empresarial_ia(
    payload: ExecutiveReportRequest,
    _admin: User = Depends(require_role(Role.ADMIN)),
    db: Session = Depends(get_db),
) -> ReporteDinamicoIA:
    # 1. Extracción de datos crudos (sin lógica de presentación)
    indicadores, top_users, top_products, critical_stock, branch_sales, periodo_humano = recopilar_metricas_bd(
        db, payload.periodo
    )

    # 2. Contexto completo para el LLM
    contexto_datos = {
        "periodo_analizado": periodo_humano,
        "indicadores_generales": indicadores,
        "clientes_destacados": [
            {
                "nombre": u.nombre or "Cliente",
                "email": u.email,
                "pedidos": u.total_pedidos,
                "facturado_bob": float(u.total_gastado),
            }
            for u in top_users
        ],
        "articulos_vendidos": [
            {
                "prenda": p.nombre_snapshot or "Prenda",
                "categoria": p.categoria,
                "unidades": p.unidades_vendidas,
                "subtotal_bob": float(p.total_facturado),
            }
            for p in top_products
        ],
        "inventario_critico": [
            {
                "prenda": s.nombre,
                "talla": str(s.talla),
                "color": str(s.color),
                "stock_restante": s.disponible,
            }
            for s in critical_stock
        ],
        "desempeno_canales": [
            {
                "canal_sucursal": b.sede,
                "ciudad": b.ciudad,
                "pedidos": b.total_pedidos,
                "total_bob": float(b.facturado),
            }
            for b in branch_sales
        ],
    }

    # 3. La IA genera títulos, estructura, tablas y análisis
    reporte_final = await generar_reporte_totalmente_libre(
        contexto_datos=contexto_datos,
        enfoque=payload.enfoque_especifico,
        modelo_ia=payload.modelo_ia,
        seed=payload.seed,
    )

    # Mapeo del nombre del modelo para la respuesta
    nombre_modelo = "Gemma-4-E2B-Instruct"
    if payload.modelo_ia == "ALTAIR_MINI":
        nombre_modelo = "Altair Mini (Scout 0.6B - Inferencia Rápida)"
    elif payload.modelo_ia == "ALTAIR_VARIABLE":
        nombre_modelo = "Altair Variable (Orquestación Híbrida Dinámica)"
    elif payload.modelo_ia == "ALTAIR":
        nombre_modelo = "Altair Principal (Gemma 4 E2B - Razonamiento Profundo)"

    # Enriquecer reporte con métricas cuantitativas y metadatos
    reporte_final.indicadores_clave = indicadores
    reporte_final.tipo_reporte = payload.tipo_reporte
    reporte_final.periodo = payload.periodo
    reporte_final.modelo_utilizado = nombre_modelo
    reporte_final.semilla_generativa = payload.seed
    reporte_final.enfoque_personalizado = payload.enfoque_especifico
    reporte_final.fecha_generacion = datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M UTC")
    reporte_final.resumen_ejecutivo = reporte_final.tesis_central
    if reporte_final.secciones:
        reporte_final.diagnostico_rendimiento = reporte_final.secciones[0].contenido

    # Despachar notificación al usuario administrador
    try:
        await dispatch_notification(
            db=db,
            user_id=_admin.id,
            titulo="Reporte Empresarial Generado",
            mensaje=f"'{reporte_final.titulo_reporte}' ({periodo_humano}) ha sido procesado con {nombre_modelo}.",
            tipo="REPORTE_GENERADO",
            payload={
                "screen": "/reports",
                "periodo": payload.periodo,
                "tipo": payload.tipo_reporte,
                "seed": payload.seed,
            },
        )
    except Exception:
        pass

    return reporte_final


# -----------------------------------------------------------------
# 4. Endpoint Resumen Ejecutivo Básico
# -----------------------------------------------------------------
@router.post(
    "/reports/executive-summary",
    summary="CU-26: Generar resumen ejecutivo inteligente de ventas y tendencias (Básico)",
    description="Analiza métricas de pedidos, prendas populares y genera un resumen gerencial con IA real.",
)
async def generar_resumen_ejecutivo_ia(
    _admin: User = Depends(require_role(Role.ADMIN)),
    db: Session = Depends(get_db),
) -> dict:
    """CU-26: Síntesis gerencial básica asistida por IA."""
    total_orders = db.scalar(select(func.count(Order.id))) or 0
    total_revenue = db.scalar(select(func.coalesce(func.sum(Order.total), Decimal("0.00")))) or Decimal("0.00")
    top_products = db.scalars(select(Product.nombre).where(Product.activo == True).limit(5)).all()

    data_summary = f"Total Pedidos: {total_orders}, Ingresos Totales: Bs {total_revenue:.2f}, Top Prendas: {', '.join(top_products)}"
    prompt = (
        f"Analiza los siguientes indicadores reales del negocio de moda y redacta un informe ejecutivo conciso "
        f"con 3 oportunidades de crecimiento: {data_summary}. "
        "REGLA CRÍTICA: CERO EMOJIS."
    )

    try:
        res, _ = await call_gemma(
            system="Eres un consultor de negocios y analista estratégico de retail de lujo. CERO EMOJIS.",
            user=prompt,
        )
        summary = res.strip() if res else ""
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Error en el motor de inferencia de IA al procesar el resumen ejecutivo: {str(exc)}",
        )

    return {
        "indicadores_base": {
            "total_pedidos": total_orders,
            "ingresos_totales_bob": float(total_revenue),
            "prendas_analizadas": len(top_products),
        },
        "informe_ejecutivo": summary,
    }
