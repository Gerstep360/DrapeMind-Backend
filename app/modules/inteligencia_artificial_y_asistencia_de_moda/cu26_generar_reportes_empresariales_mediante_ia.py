"""CU-26: Generar reportes empresariales mediante IA real.
Paquete: Inteligencia artificial y asistencia de moda (PK-05).
"""
import json
import re
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
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
from app.services.push_notifications import dispatch_notification

router = APIRouter()


# 1. Esquema Pydantic para el contenido cualitativo generado por la IA
class AIReportContent(BaseModel):
    resumen_ejecutivo: str = Field(description="Síntesis directiva del desempeño del negocio")
    diagnostico_rendimiento: str = Field(description="Diagnóstico operativo y financiero detallado")
    analisis_enfoque: str | None = Field(None, description="Respuesta analítica al enfoque específico solicitado por el directorio")
    cuellos_de_botella: list[str] = Field(description="Entre 2 y 4 cuellos de botella reales detectados según las métricas")
    recomendaciones_estrategicas: list[str] = Field(description="Entre 3 y 5 acciones concretas priorizadas")

    @field_validator("cuellos_de_botella", "recomendaciones_estrategicas", mode="before")
    @classmethod
    def parse_list_items(cls, v: Any) -> list[str]:
        if isinstance(v, str):
            lines = [line.strip().lstrip("•-*0123456789. ") for line in v.split("\n") if line.strip()]
            return [l for l in lines if l]
        if isinstance(v, list):
            return [str(x).strip() for x in v if str(x).strip()]
        return []


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


# 2. Motor de inferencia cualitativa con IA real
async def generar_analisis_ia(
    contexto_datos: dict,
    enfoque: str | None,
    modelo_ia: str | None = None,
    seed: int | None = None,
) -> AIReportContent:
    """Invoca el LLM exigiendo Structured Output JSON validado contra Pydantic."""
    system_prompt = (
        "Eres un consultor estratégico senior de retail de lujo y alta costura. "
        "Analiza rigurosamente los datos cuantitativos provistos del negocio y genera un diagnóstico "
        "estratégico directivo en formato JSON válido según el esquema solicitado. CERO EMOJIS."
    )

    user_prompt = f"""
Métricas y datos operativos reales del negocio:
{json.dumps(contexto_datos, indent=2, default=str, ensure_ascii=False)}

Enfoque específico solicitado por el directorio:
{enfoque or "Diagnóstico general de rentabilidad, eficiencia operativa y gestión de atelier"}

Genera el análisis estratégico completo en formato JSON con la siguiente estructura exacta:
{{
  "resumen_ejecutivo": "Síntesis directiva del desempeño del negocio basada en las métricas",
  "diagnostico_rendimiento": "Diagnóstico operativo, comercial y financiero exhaustivo",
  "analisis_enfoque": "Análisis y respuesta profunda al enfoque específico solicitado por el directorio",
  "cuellos_de_botella": [
    "Cuello de botella 1 detectado en los datos",
    "Cuello de botella 2 detectado en los datos"
  ],
  "recomendaciones_estrategicas": [
    "Acción estratégica priorizada 1",
    "Acción estratégica priorizada 2",
    "Acción estratégica priorizada 3"
  ]
}}

REGLAS ESTRICTAS:
1. Responde EXCLUSIVAMENTE con el objeto JSON válido. Cero texto o explicaciones antes o después del JSON.
2. CERO EMOJIS.
3. No inventes métricas cuantitativas que contradigan los datos provistos.
4. Moneda en Bolivianos (Bs).
"""

    try:
        raw_response, _ = await call_gemma(
            system=system_prompt,
            user=user_prompt,
            response_format={"type": "json_object"},
            seed=seed,
            temperature=0.35,
            max_tokens=1600,
        )
        data = _extract_json_payload(raw_response)
        return AIReportContent.model_validate(data)
    except Exception as e:
        raise HTTPException(
            status_code=502,
            detail=f"Error en el motor de inferencia de IA al procesar el reporte: {str(e)}",
        )


# 3. Extracción de métricas de base de datos (SQLAlchemy)
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

    # Top Clientes
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
        .limit(5)
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
            .limit(5)
        )
        top_users = db.execute(fallback_users_query).all()

    # Top Prendas
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
    top_products = db.execute(top_products_query).all()

    # Stock Crítico
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
    critical_stock = db.execute(critical_stock_query).all()

    # Ventas por Sede
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
    branch_sales = db.execute(branch_sales_query).all()

    return indicadores, top_users, top_products, critical_stock, branch_sales, periodo_humano


# 4. Construcción de tablas analíticas basadas en datos reales
def armar_tablas_analiticas(top_users, top_products, critical_stock, branch_sales) -> list[ReportTable]:
    tablas: list[ReportTable] = []

    if top_users:
        filas_usuarios = [
            [
                u.nombre or f"Cliente #{idx+1}",
                u.email or "Sin correo",
                f"{u.total_pedidos} orden{'es' if u.total_pedidos != 1 else ''}",
                f"Bs {float(u.total_gastado):,.2f}",
                "VIP Atelier" if float(u.total_gastado) >= 1500 or u.total_pedidos >= 3 else "Frecuente",
            ]
            for idx, u in enumerate(top_users)
        ]
        tablas.append(
            ReportTable(
                titulo="Clientes con Mayor Volumen de Compra y Facturación",
                columnas=["Cliente", "Correo de Contacto", "Pedidos Realizados", "Inversión Total", "Segmento"],
                filas=filas_usuarios,
                resumen=f"El cliente con mayor volumen de compra es {top_users[0].nombre or 'Cliente Principal'} con una inversión total de Bs {float(top_users[0].total_gastado):,.2f}.",
            )
        )

    if top_products:
        filas_prendas = [
            [
                p.nombre_snapshot or "Prenda Sastrera",
                p.categoria or "Línea General",
                f"{p.unidades_vendidas} uds",
                f"Bs {float(p.total_facturado):,.2f}",
                "Alta Rotación" if p.unidades_vendidas >= 4 else "Demanda Moderada",
            ]
            for p in top_products
        ]
        tablas.append(
            ReportTable(
                titulo="Prendas Sastreras con Mayor Demanda y Rotación Comercial",
                columnas=["Prenda / Modelo", "Colección", "Unidades Vendidas", "Facturación Bruta", "Rotación"],
                filas=filas_prendas,
                resumen=f"La prenda líder en ventas es '{top_products[0].nombre_snapshot}' con {top_products[0].unidades_vendidas} unidades desplazadas.",
            )
        )

    if critical_stock:
        filas_stock = [
            [
                s.nombre,
                s.categoria,
                str(s.talla),
                str(s.color),
                f"{s.disponible} uds",
                "CRÍTICA (URGENTE)" if s.disponible <= 1 else "Reposición Regular",
            ]
            for s in critical_stock
        ]
        tablas.append(
            ReportTable(
                titulo="Inventario en Umbral de Stock Crítico (<= 3 Unidades)",
                columnas=["Prenda", "Línea", "Talla", "Color", "Stock Disponible", "Prioridad Taller"],
                filas=filas_stock,
                resumen=f"Se identifican {len(critical_stock)} variantes prioritarias para reposición inmediata con proveedores de tela.",
            )
        )

    if branch_sales and any(b.total_pedidos > 0 for b in branch_sales):
        filas_canales = [
            [
                b.sede,
                b.ciudad,
                f"{b.total_pedidos} pedidos",
                f"Bs {float(b.facturado):,.2f}",
            ]
            for b in branch_sales
        ]
        tablas.append(
            ReportTable(
                titulo="Distribución de Facturación por Sedes y Canales",
                columnas=["Canal / Sucursal", "Ciudad", "Pedidos", "Facturación Neta"],
                filas=filas_canales,
                resumen=f"Canal principal: {branch_sales[0].sede} con Bs {float(branch_sales[0].facturado):,.2f}.",
            )
        )

    return tablas


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


# 5. Endpoint Principal CU-26 con IA Real y Structured Outputs
@router.post(
    "/reports/generate",
    response_model=ExecutiveReportResponse,
    summary="CU-26: Generar informe empresarial con IA real",
    description="Extrae datos reales con SQLAlchemy y delega a la IA el análisis cualitativo en JSON estructurado.",
)
async def generar_informe_empresarial_ia(
    payload: ExecutiveReportRequest,
    _admin: User = Depends(require_role(Role.ADMIN)),
    db: Session = Depends(get_db),
) -> ExecutiveReportResponse:
    # 1. Extracción de métricas de BD (SQLAlchemy)
    indicadores, top_users, top_products, critical_stock, branch_sales, periodo_humano = recopilar_metricas_bd(
        db, payload.periodo
    )

    # 2. Ensamblado del contexto real para el modelo de IA
    contexto_analitico = {
        "tipo_reporte": payload.tipo_reporte,
        "periodo": periodo_humano,
        "indicadores_generales": indicadores,
        "top_clientes": [
            {
                "nombre": u.nombre or "Cliente",
                "email": u.email,
                "pedidos": u.total_pedidos,
                "total_gastado": float(u.total_gastado),
            }
            for u in top_users
        ],
        "top_prendas": [
            {
                "prenda": p.nombre_snapshot or "Prenda",
                "categoria": p.categoria,
                "unidades": p.unidades_vendidas,
                "facturado": float(p.total_facturado),
            }
            for p in top_products
        ],
        "stock_critico": [
            {
                "prenda": s.nombre,
                "talla": str(s.talla),
                "color": str(s.color),
                "disponible": s.disponible,
                "categoria": s.categoria,
            }
            for s in critical_stock
        ],
        "ventas_por_sede": [
            {
                "sede": b.sede,
                "ciudad": b.ciudad,
                "pedidos": b.total_pedidos,
                "facturado": float(b.facturado),
            }
            for b in branch_sales
        ],
    }

    # 3. La IA procesa y genera todo el análisis cualitativo estructurado
    analisis_ia = await generar_analisis_ia(
        contexto_datos=contexto_analitico,
        enfoque=payload.enfoque_especifico,
        modelo_ia=payload.modelo_ia,
        seed=payload.seed,
    )

    # 4. Construcción de tablas analíticas basadas en datos duros
    tablas = armar_tablas_analiticas(top_users, top_products, critical_stock, branch_sales)

    # Mapeo del nombre del modelo para la respuesta
    nombre_modelo = "Gemma-4-E2B-Instruct"
    if payload.modelo_ia == "ALTAIR_MINI":
        nombre_modelo = "Altair Mini (Scout 0.6B - Inferencia Rápida)"
    elif payload.modelo_ia == "ALTAIR_VARIABLE":
        nombre_modelo = "Altair Variable (Orquestación Híbrida Dinámica)"
    elif payload.modelo_ia == "ALTAIR":
        nombre_modelo = "Altair Principal (Gemma 4 E2B - Razonamiento Profundo)"

    # Despachar notificación al usuario administrador
    try:
        await dispatch_notification(
            db=db,
            user_id=_admin.id,
            titulo="Reporte Empresarial Generado",
            mensaje=f"El informe estratégico de {payload.tipo_reporte} ({periodo_humano}) ha sido procesado con {nombre_modelo}.",
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

    # 5. Respuesta limpia y validada
    return ExecutiveReportResponse(
        tipo_reporte=payload.tipo_reporte,
        periodo=payload.periodo,
        modelo_utilizado=nombre_modelo,
        semilla_generativa=payload.seed,
        angulo_estrategico=None,
        indicadores_clave=indicadores,
        resumen_ejecutivo=analisis_ia.resumen_ejecutivo,
        diagnostico_rendimiento=analisis_ia.diagnostico_rendimiento,
        enfoque_personalizado=analisis_ia.analisis_enfoque,
        tablas_analiticas=tablas,
        cuellos_de_botella=analisis_ia.cuellos_de_botella,
        recomendaciones_estrategicas=analisis_ia.recomendaciones_estrategicas,
        fecha_generacion=datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M UTC"),
    )
