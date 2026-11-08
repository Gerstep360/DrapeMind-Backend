"""Resume only persisted, explicitly authorized purchases; never synthesize an offline approval."""

import asyncio
import logging
from datetime import datetime, timezone
from sqlalchemy import select, or_
from starlette.concurrency import run_in_threadpool
from app.core.tenancy import system_scope
from app.segundo_parcial.cu23_pagos.cu23_modelos import DeferredPurchase
from app.segundo_parcial.cu23_pagos.cu23_compras_diferidas import process, TERMINAL

logger = logging.getLogger("drapemind.deferred")


def tick():
    from app.db.session import SessionLocal

    now = datetime.now(timezone.utc)
    with SessionLocal() as db, system_scope(db):
        candidates = list(
            db.execute(
                select(DeferredPurchase.id, DeferredPurchase.tenant_id)
                .where(
                    DeferredPurchase.estado.not_in(TERMINAL),
                    or_(
                        DeferredPurchase.siguiente_intento.is_(None),
                        DeferredPurchase.siguiente_intento <= now,
                    ),
                    or_(
                        DeferredPurchase.estado != "REQUIERE_METODO",
                        DeferredPurchase.vence_at <= now,
                    ),
                )
                .order_by(
                    DeferredPurchase.siguiente_intento.asc().nulls_first(),
                    DeferredPurchase.id,
                )
                .limit(30)
            )
        )
    for identity, tenant in candidates:
        try:
            with SessionLocal(tenant_id=tenant) as db:
                row = db.get(DeferredPurchase, identity)
                if row:
                    process(db, row)
        except Exception:
            logger.warning(
                "Conciliación diferida pendiente; se reintentará en el siguiente ciclo."
            )


async def run():
    while True:
        await asyncio.sleep(45)
        try:
            await run_in_threadpool(tick)
        except Exception:
            logger.warning("No se pudo consultar la cola de compras diferidas.")
