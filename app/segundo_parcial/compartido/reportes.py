from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import json, re
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from app.api.deps import get_current_user, require_roles
from app.db.session import get_db
from app.models import (
    Order,
    OrderItem,
    Payment,
    Product,
    ProductVariant,
    Branch,
    BranchStock,
    Role,
    User,
)
from app.models.saas import Tenant
from app.services.saas import require_active_subscription
from app.services.ai import call_nvidia
from app.services.ai_errors import AIProviderError
from app.services.financials import net_payments
from app.segundo_parcial.cu24_pedidos.cu24_historial import download_receipt, get_order
from app.segundo_parcial.compartido.comercio_modelos import (
    BusinessReport,
    CheckoutConfirmation,
)
from app.segundo_parcial.compartido.pdf import document

admin = require_roles(Role.ADMIN)


def pdf_response(content, filename):
    return Response(
        content,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


class ReportInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    consulta: str = Field(min_length=5, max_length=1000)
    desde: date | None = None
    hasta: date | None = None
    sucursal_id: int | None = Field(default=None, gt=0)
    entrada: Literal["TEXTO", "VOZ"] = "TEXTO"

    @model_validator(mode="after")
    def interval(self):
        if bool(self.desde) != bool(self.hasta):
            raise ValueError("Indica ambas fechas o ninguna")
        if self.desde and (
            self.hasta < self.desde or (self.hasta - self.desde).days > 366
        ):
            raise ValueError("El periodo debe ser válido y de hasta 366 días")
        if self.hasta and self.hasta > datetime.now(timezone.utc).date():
            raise ValueError("La fecha final no puede estar en el futuro")
        return self


def report_dates(payload):
    today = datetime.now(timezone.utc).date()
    if payload.desde:
        return payload.desde, payload.hasta
    q = payload.consulta.casefold()
    if "ayer" in q:
        return today - timedelta(days=1), today - timedelta(days=1)
    if "hoy" in q:
        return today, today
    if "mes actual" in q or "este mes" in q:
        return today.replace(day=1), today
    days = 7 if "semana" in q else 30
    match = re.search(r"(?:últimos|ultimos)\s+(\d+)\s+d[ií]as", q)
    if match:
        days = int(match[1])
        if not 1 <= days <= 366:
            raise HTTPException(422, "El periodo solicitado debe ser de 1 a 366 días")
    return today - timedelta(days=days - 1), today


def facts(db, payload, user):
    start, end = report_dates(payload)
    lower = datetime.combine(start, datetime.min.time(), tzinfo=timezone.utc)
    upper = datetime.combine(
        end + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc
    )
    branch = db.get(Branch, payload.sucursal_id) if payload.sucursal_id else None
    if payload.sucursal_id and not branch:
        raise HTTPException(404, "Sucursal no encontrada en esta empresa")
    filters = [
        Order.paid_at >= lower,
        Order.paid_at < upper,
        Order.estado != "CANCELADO",
    ]
    if branch:
        filters.append(Order.sucursal_id == branch.id)
    orders = select(Order.id).where(*filters)
    count = db.scalar(select(func.count(Order.id)).where(*filters)) or 0
    payment_filters = [Payment.paid_at >= lower, Payment.paid_at < upper]
    if branch:
        payment_filters.append(
            Payment.pedido_id.in_(
                select(Order.id).where(Order.sucursal_id == branch.id)
            )
        )
    net = net_payments(db, *payment_filters)
    top = db.execute(
        select(OrderItem.nombre_snapshot, func.sum(OrderItem.cantidad))
        .where(OrderItem.pedido_id.in_(orders))
        .group_by(OrderItem.nombre_snapshot)
        .order_by(func.sum(OrderItem.cantidad).desc(), OrderItem.nombre_snapshot)
        .limit(10)
    ).all()
    stock_query = select(BranchStock).where(BranchStock.activo.is_(True))
    if branch:
        stock_query = stock_query.where(BranchStock.sucursal_id == branch.id)
    stock = list(db.scalars(stock_query))
    tenant = db.get(Tenant, user.tenant_id)
    return {
        "empresa": tenant.name,
        "moneda": "BOB",
        "desde": str(start),
        "hasta": str(end),
        "sucursal_id": payload.sucursal_id,
        "sucursal": branch.nombre if branch else "Todas las sucursales",
        "pedidos_pagados": count,
        "ingreso_neto_cobrado": str(Decimal(net).quantize(Decimal(".01"))),
        "prendas_vendidas": [
            {"nombre": name, "cantidad": int(qty)} for name, qty in top
        ],
        "inventario_actual": {
            "fecha_consulta": datetime.now(timezone.utc).isoformat(),
            "unidades_disponibles": sum(
                max(0, s.stock_total - s.stock_reservado) for s in stock
            ),
            "variantes_con_stock_bajo": sum(
                s.stock_total - s.stock_reservado <= s.stock_minimo for s in stock
            ),
        },
        "alcance": "Ingresos: cobros aprobados y devoluciones de efectivo dentro del periodo, incluso si la venta original fue anterior; excluye créditos de cambio. Prendas: unidades de pedidos pagados, incluidos reemplazos. Inventario: estado actual, no reconstrucción histórica.",
    }


def report_out(row):
    return {
        "id": row.id,
        "consulta": row.consulta,
        "entrada": row.entrada,
        "created_at": row.created_at,
        **row.resultado,
    }
