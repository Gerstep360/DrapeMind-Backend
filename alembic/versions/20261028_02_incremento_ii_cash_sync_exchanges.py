"""Incremento II CU-15 a CU-20: operaciones, auditoría y cambios de prendas."""
from alembic import op
revision = '20261028_02'
down_revision = '20261028_01'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TYPE metodo_pago ADD VALUE IF NOT EXISTS 'CREDITO_CAMBIO'")
    op.execute("""
CREATE TABLE offline_operaciones (
	id BIGSERIAL NOT NULL,
	usuario_id BIGINT NOT NULL,
	sucursal_id BIGINT NOT NULL,
	operacion_id VARCHAR(36) NOT NULL,
	tipo VARCHAR(20) NOT NULL,
	payload_hash VARCHAR(64) NOT NULL,
	payload JSONB NOT NULL,
	estado VARCHAR(20) NOT NULL,
	resultado JSONB,
	error JSONB,
	intentos INTEGER NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	tenant_id BIGINT NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT uq_offline_operation_owner UNIQUE (tenant_id, usuario_id, operacion_id),
	CONSTRAINT ck_sync_type CHECK (tipo IN ('RESERVATION','SALE','PICKUP')),
	CONSTRAINT ck_sync_state CHECK (estado IN ('PENDING','CONFIRMED','CONFLICT','REJECTED')),
	FOREIGN KEY(tenant_id) REFERENCES saas_tenants (id) ON DELETE RESTRICT,
	CONSTRAINT uq_offline_operaciones_id_tenant UNIQUE (id, tenant_id),
	CONSTRAINT fk_offline_operaciones_usuario_id_tenant FOREIGN KEY(usuario_id, tenant_id) REFERENCES usuarios (id, tenant_id),
	CONSTRAINT fk_offline_operaciones_sucursal_id_tenant FOREIGN KEY(sucursal_id, tenant_id) REFERENCES sucursales (id, tenant_id)
)

""")
    op.execute('CREATE INDEX ix_offline_operaciones_tenant_id ON offline_operaciones (tenant_id)')
    op.execute("""
CREATE TABLE offline_operaciones_auditoria (
	id BIGSERIAL NOT NULL,
	operacion_id BIGINT NOT NULL,
	actor_id BIGINT NOT NULL,
	accion VARCHAR(30) NOT NULL,
	detalle JSONB NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	tenant_id BIGINT NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(tenant_id) REFERENCES saas_tenants (id) ON DELETE RESTRICT,
	CONSTRAINT uq_offline_operaciones_auditoria_id_tenant UNIQUE (id, tenant_id),
	CONSTRAINT fk_offline_operaciones_auditoria_operacion_id_tenant FOREIGN KEY(operacion_id, tenant_id) REFERENCES offline_operaciones (id, tenant_id),
	CONSTRAINT fk_offline_operaciones_auditoria_actor_id_tenant FOREIGN KEY(actor_id, tenant_id) REFERENCES usuarios (id, tenant_id)
)

""")
    op.execute('CREATE INDEX ix_offline_operaciones_auditoria_tenant_id ON offline_operaciones_auditoria (tenant_id)')
    op.execute("""
CREATE TABLE cambios_prendas (
	id BIGSERIAL NOT NULL,
	operacion_id VARCHAR(36) NOT NULL,
	payload_hash VARCHAR(64) NOT NULL,
	pedido_origen_id BIGINT NOT NULL,
	pedido_nuevo_id BIGINT NOT NULL,
	sucursal_id BIGINT NOT NULL,
	actor_id BIGINT NOT NULL,
	motivo VARCHAR(300) NOT NULL,
	credito NUMERIC(12, 2) NOT NULL,
	total_nuevo NUMERIC(12, 2) NOT NULL,
	diferencia NUMERIC(12, 2) NOT NULL,
	efectivo_recibido NUMERIC(12, 2) NOT NULL,
	efectivo_devuelto NUMERIC(12, 2) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	tenant_id BIGINT NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT uq_exchange_operation UNIQUE (tenant_id, operacion_id),
	CONSTRAINT ck_exchange_amounts CHECK (credito >= 0 AND total_nuevo >= 0 AND efectivo_recibido >= 0 AND efectivo_devuelto >= 0),
	UNIQUE (pedido_nuevo_id),
	FOREIGN KEY(tenant_id) REFERENCES saas_tenants (id) ON DELETE RESTRICT,
	CONSTRAINT uq_cambios_prendas_id_tenant UNIQUE (id, tenant_id),
	CONSTRAINT fk_cambios_prendas_actor_id_tenant FOREIGN KEY(actor_id, tenant_id) REFERENCES usuarios (id, tenant_id),
	CONSTRAINT fk_cambios_prendas_pedido_nuevo_id_tenant FOREIGN KEY(pedido_nuevo_id, tenant_id) REFERENCES pedidos (id, tenant_id),
	CONSTRAINT fk_cambios_prendas_pedido_origen_id_tenant FOREIGN KEY(pedido_origen_id, tenant_id) REFERENCES pedidos (id, tenant_id),
	CONSTRAINT fk_cambios_prendas_sucursal_id_tenant FOREIGN KEY(sucursal_id, tenant_id) REFERENCES sucursales (id, tenant_id)
)

""")
    op.execute('CREATE INDEX ix_cambios_prendas_tenant_id ON cambios_prendas (tenant_id)')
    op.execute("""
CREATE TABLE cambios_prendas_devoluciones (
	id BIGSERIAL NOT NULL,
	cambio_id BIGINT NOT NULL,
	item_pedido_id BIGINT NOT NULL,
	cantidad INTEGER NOT NULL,
	credito NUMERIC(12, 2) NOT NULL,
	tenant_id BIGINT NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT ck_exchange_return_qty CHECK (cantidad > 0),
	FOREIGN KEY(tenant_id) REFERENCES saas_tenants (id) ON DELETE RESTRICT,
	CONSTRAINT uq_cambios_prendas_devoluciones_id_tenant UNIQUE (id, tenant_id),
	CONSTRAINT fk_cambios_prendas_devoluciones_cambio_id_tenant FOREIGN KEY(cambio_id, tenant_id) REFERENCES cambios_prendas (id, tenant_id),
	CONSTRAINT fk_cambios_prendas_devoluciones_item_pedido_id_tenant FOREIGN KEY(item_pedido_id, tenant_id) REFERENCES items_pedido (id, tenant_id)
)

""")
    op.execute('CREATE INDEX ix_cambios_prendas_devoluciones_tenant_id ON cambios_prendas_devoluciones (tenant_id)')
    for table in ('offline_operaciones', 'offline_operaciones_auditoria', 'cambios_prendas', 'cambios_prendas_devoluciones'):
        op.execute(f'ALTER TABLE {table} ENABLE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE {table} FORCE ROW LEVEL SECURITY')
        op.execute(f"CREATE POLICY tenant_isolation ON {table} USING (current_setting('app.saas_system',true)='true' OR tenant_id=NULLIF(current_setting('app.tenant_id',true),'')::bigint) WITH CHECK (current_setting('app.saas_system',true)='true' OR tenant_id=NULLIF(current_setting('app.tenant_id',true),'')::bigint)")


def downgrade():
    # PostgreSQL keeps the additional payment enum label to preserve payment history.
    op.drop_table('cambios_prendas_devoluciones')
    op.drop_table('cambios_prendas')
    op.drop_table('offline_operaciones_auditoria')
    op.drop_table('offline_operaciones')
