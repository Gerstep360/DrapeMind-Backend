from fastapi import HTTPException
from sqlalchemy import event, select, inspect
from sqlalchemy.orm import Session, with_loader_criteria
from sqlalchemy.sql.elements import TextClause
from app.core.tenancy import tenant_context
from app.models.saas import TenantOwned


class TenantSession(Session):
    def __init__(self, *args, tenant_id=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.info['tenant_id'] = tenant_id if tenant_id is not None else tenant_context.get()

    def get(self, entity, ident, **kwargs):
        value = super().get(entity, ident, **kwargs)
        if isinstance(value, TenantOwned) and not self.info.get('saas_system') and value.tenant_id != self.info.get('tenant_id'):
            return None
        return value


def apply_database_scope(db):
    if not isinstance(db, TenantSession) or not db.in_transaction():
        return
    connection = db.connection()
    if connection.dialect.name == 'postgresql':
        connection.exec_driver_sql("SELECT set_config('app.tenant_id', %s, true), set_config('app.saas_system', %s, true)", (str(db.info.get('tenant_id') or 0), 'true' if db.info.get('saas_system') else 'false'))


def bind_tenant(db, tenant_id):
    if db.info.get('tenant_id') not in (None, tenant_id):
        db.expunge_all()
    db.info['tenant_id'] = tenant_id
    apply_database_scope(db)


@event.listens_for(TenantSession, 'after_begin')
def database_scope(db, transaction, connection):
    if connection.dialect.name == 'postgresql':
        connection.exec_driver_sql("SELECT set_config('app.tenant_id', %s, true), set_config('app.saas_system', %s, true)", (str(db.info.get('tenant_id') or 0), 'true' if db.info.get('saas_system') else 'false'))


@event.listens_for(TenantSession, 'do_orm_execute')
def scope_statement(state):
    db = state.session
    if db.info.get('saas_system'):
        return
    if isinstance(state.statement, TextClause):
        raise HTTPException(403, 'Las consultas SQL sin ámbito empresarial no están permitidas')
    if state.is_update and any(getattr(key,'name',key)=='tenant_id' for key in (getattr(state.statement,'_values',None) or {})):
        raise HTTPException(403,'No se permite trasladar registros entre empresas')
    if state.is_insert and state.bind_mapper is not None and issubclass(state.bind_mapper.class_,TenantOwned):
        raise HTTPException(403,'Crea los registros mediante entidades con validación empresarial')
    tenant_id = db.info.get('tenant_id') or 0
    if state.is_select or state.is_update or state.is_delete:
        state.statement = state.statement.options(with_loader_criteria(TenantOwned, lambda cls: cls.tenant_id == tenant_id, include_aliases=True))


@event.listens_for(TenantSession, 'before_flush')
def validate_ownership(db, flush_context, instances):
    if db.info.get('saas_system'):
        return
    tenant_id = db.info.get('tenant_id')
    objects = list(db.new) + list(db.dirty) + list(db.deleted)
    for obj in objects:
        if not isinstance(obj, TenantOwned):
            continue
        if not tenant_id:
            raise HTTPException(403, 'Selecciona una empresa autorizada')
        if obj in db.new and obj.tenant_id is None:
            obj.tenant_id = tenant_id
        if obj.tenant_id != tenant_id:
            raise HTTPException(404, 'Recurso no encontrado en esta empresa')
        for column in inspect(type(obj)).columns:
            if column.name == 'tenant_id': continue
            for fk in column.foreign_keys:
                if fk.column.name != 'id' or fk.column.table.name == 'saas_tenants': continue
                parent = next((m.class_ for m in type(obj).registry.mappers if m.local_table is fk.column.table), None)
                identity = getattr(obj, column.name)
                if identity is not None and parent and issubclass(parent, TenantOwned) and db.get(parent, identity) is None:
                    # An unflushed parent in this transaction is allowed; composite FK is the backstop.
                    if not any(isinstance(p, parent) and p.id == identity and p.tenant_id == tenant_id for p in db.new):
                        raise HTTPException(404, 'La relación no pertenece a esta empresa')
    from app.services.saas import enforce_pending_branch_limit
    enforce_pending_branch_limit(db, objects)
