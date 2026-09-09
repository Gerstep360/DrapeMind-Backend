"""Conversation lifecycle; one existing AISession owns messages and compact state."""
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from app.models import AISession, Product
from app.services.ai_memory import load_ai_memory, build_session_summary
from app.services.chat_context import read_context


def owned_session(db: Session, user_id: int, session_id: int, lock: bool = False):
    stmt = select(AISession).where(AISession.id == session_id, AISession.usuario_id == user_id)
    if lock:
        stmt = stmt.with_for_update(nowait=True).execution_options(populate_existing=True)
    try:
        session = db.scalar(stmt)
    except OperationalError as exc:
        db.rollback()
        if getattr(exc.orig, "pgcode", None) != "55P03":
            raise
        raise HTTPException(409, "La conversación está procesando una consulta. Intenta de nuevo al finalizar.") from exc
    if not session or session.estado != "ACTIVA":
        raise HTTPException(404, "Conversación no encontrada o cerrada")
    return session


def delete_chat(db: Session, user_id: int, session_id: int):
    session = owned_session(db, user_id, session_id, lock=True)
    # Existing FK cascades delete interactions and their recommendations.
    db.delete(session)
    db.commit()


def select_product(db: Session, user_id: int, session_id: int, product_id: int):
    session = owned_session(db, user_id, session_id, lock=True)
    state = read_context(load_ai_memory(session.resumen_contexto))
    entity = next((item for item in state.recent + state.previous
                   if item.type == "product" and item.id == product_id), None)
    if not entity:
        raise HTTPException(409, "Esta prenda no pertenece a las opciones de la conversación")
    product = db.get(Product, product_id)
    if not product or not product.activo:
        raise HTTPException(404, "Prenda no disponible")
    entity.label = product.nombre[:100]
    state.selected = [entity]
    followup = state.pending or entity.label
    session.resumen_contexto = build_session_summary("", state.model_dump())
    db.commit()
    return {"selected": entity.model_dump(), "followup": followup}
