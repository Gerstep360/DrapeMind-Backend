"""Bind a physical push token only to the authenticated identity's memberships."""
import hashlib
from sqlalchemy import select, func
from app.core.tenancy import system_scope
from app.models import User, UserStatus, UserDevice


def _lock(db, token):
    if db.bind.dialect.name == 'postgresql':
        key = int.from_bytes(hashlib.blake2b(token.encode(), digest_size=8).digest(), 'big', signed=True)
        db.connection().exec_driver_sql('SELECT pg_advisory_xact_lock(%s)', (key,))


def _owners(db, user):
    if not user.customer_account_id:
        return [user]
    return list(db.scalars(select(User).where(User.customer_account_id == user.customer_account_id, User.estado == UserStatus.ACTIVO)))


def register(db, user, payload):
    _lock(db, payload.token)
    with system_scope(db):
        owners = _owners(db, user)
        owner_ids = {owner.id for owner in owners}
        existing = list(db.scalars(select(UserDevice).where(UserDevice.token == payload.token).with_for_update()))
        if payload.dispositivo_id:
            for old in db.scalars(select(UserDevice).where(UserDevice.usuario_id.in_(owner_ids), UserDevice.dispositivo_id == payload.dispositivo_id, UserDevice.token != payload.token)):
                old.activo = False
        for row in existing:
            if row.usuario_id not in owner_ids:
                row.activo = False  # The same phone was signed into a different identity.
        by_user = {row.usuario_id: row for row in existing}
        for owner in owners:
            row = by_user.get(owner.id)
            if row is None:
                row = UserDevice(tenant_id=owner.tenant_id, usuario_id=owner.id, token=payload.token)
                db.add(row)
            row.dispositivo_id = payload.dispositivo_id
            row.plataforma = payload.plataforma
            row.modelo = payload.modelo
            row.web_subscription = getattr(payload, 'web_subscription', None)
            row.activo = True
            row.ultimo_uso = func.now()
        db.commit()
    return len(owners)


def unregister(db, user, token):
    _lock(db, token)
    with system_scope(db):
        owner_ids = [row.id for row in _owners(db, user)]
        rows = db.scalars(select(UserDevice).where(UserDevice.token == token, UserDevice.usuario_id.in_(owner_ids)))
        for row in rows:
            row.activo = False
        db.commit()
