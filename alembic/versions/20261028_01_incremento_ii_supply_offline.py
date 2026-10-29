"""Incremento II: abastecimiento y recibos idempotentes de reservas offline."""
from alembic import op
revision = '20261028_01'
down_revision = '20261025_02'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
CREATE TABLE abastecimiento_pedidos (
	id BIGSERIAL NOT NULL,
	request_id VARCHAR(36) NOT NULL,
	payload_hash VARCHAR(64) NOT NULL,
	proveedor_id BIGINT NOT NULL,
	sucursal_id BIGINT NOT NULL,
	creado_por_id BIGINT NOT NULL,
	recibido_por_id BIGINT,
	estado VARCHAR(20) NOT NULL,
	observacion TEXT,
	total NUMERIC(12, 2) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	recibido_at TIMESTAMP WITH TIME ZONE,
	tenant_id BIGINT NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT uq_supply_request UNIQUE (tenant_id, request_id),
	CONSTRAINT ck_supply_state CHECK (estado IN ('SOLICITADO','CONFIRMADO','RECIBIDO','CANCELADO')),
	CONSTRAINT ck_supply_total CHECK (total >= 0),
	FOREIGN KEY(tenant_id) REFERENCES saas_tenants (id) ON DELETE RESTRICT,
	CONSTRAINT uq_abastecimiento_pedidos_id_tenant UNIQUE (id, tenant_id),
	CONSTRAINT fk_abastecimiento_pedidos_sucursal_id_tenant FOREIGN KEY(sucursal_id, tenant_id) REFERENCES sucursales (id, tenant_id),
	CONSTRAINT fk_abastecimiento_pedidos_creado_por_id_tenant FOREIGN KEY(creado_por_id, tenant_id) REFERENCES usuarios (id, tenant_id),
	CONSTRAINT fk_abastecimiento_pedidos_recibido_por_id_tenant FOREIGN KEY(recibido_por_id, tenant_id) REFERENCES usuarios (id, tenant_id),
	CONSTRAINT fk_abastecimiento_pedidos_proveedor_id_tenant FOREIGN KEY(proveedor_id, tenant_id) REFERENCES proveedores (id, tenant_id)
)

""")
    op.execute('CREATE INDEX ix_abastecimiento_pedidos_tenant_id ON abastecimiento_pedidos (tenant_id)')
    op.execute("""
CREATE TABLE abastecimiento_items (
	id BIGSERIAL NOT NULL,
	pedido_id BIGINT NOT NULL,
	suministro_id BIGINT NOT NULL,
	variante_id BIGINT,
	nombre VARCHAR(150) NOT NULL,
	cantidad INTEGER NOT NULL,
	precio_unitario NUMERIC(10, 2) NOT NULL,
	tenant_id BIGINT NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT ck_supply_quantity CHECK (cantidad > 0),
	FOREIGN KEY(tenant_id) REFERENCES saas_tenants (id) ON DELETE RESTRICT,
	CONSTRAINT uq_abastecimiento_items_id_tenant UNIQUE (id, tenant_id),
	CONSTRAINT fk_abastecimiento_items_pedido_id_tenant FOREIGN KEY(pedido_id, tenant_id) REFERENCES abastecimiento_pedidos (id, tenant_id) ON DELETE CASCADE,
	CONSTRAINT fk_abastecimiento_items_suministro_id_tenant FOREIGN KEY(suministro_id, tenant_id) REFERENCES proveedor_suministros (id, tenant_id),
	CONSTRAINT fk_abastecimiento_items_variante_id_tenant FOREIGN KEY(variante_id, tenant_id) REFERENCES variantes_producto (id, tenant_id)
)

""")
    op.execute('CREATE INDEX ix_abastecimiento_items_tenant_id ON abastecimiento_items (tenant_id)')
    op.execute("""
CREATE TABLE offline_reservas_recibidas (
	id BIGSERIAL NOT NULL,
	usuario_id BIGINT NOT NULL,
	operacion_id VARCHAR(36) NOT NULL,
	payload_hash VARCHAR(64) NOT NULL,
	reserva_id BIGINT NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	tenant_id BIGINT NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT uq_offline_reservation_operation UNIQUE (tenant_id, usuario_id, operacion_id),
	FOREIGN KEY(tenant_id) REFERENCES saas_tenants (id) ON DELETE RESTRICT,
	CONSTRAINT uq_offline_reservas_recibidas_id_tenant UNIQUE (id, tenant_id),
	CONSTRAINT fk_offline_reservas_recibidas_usuario_id_tenant FOREIGN KEY(usuario_id, tenant_id) REFERENCES usuarios (id, tenant_id),
	CONSTRAINT fk_offline_reservas_recibidas_reserva_id_tenant FOREIGN KEY(reserva_id, tenant_id) REFERENCES reservas (id, tenant_id)
)

""")
    op.execute('CREATE INDEX ix_offline_reservas_recibidas_tenant_id ON offline_reservas_recibidas (tenant_id)')
    for table in ('abastecimiento_pedidos', 'abastecimiento_items', 'offline_reservas_recibidas'):
        op.execute(f'ALTER TABLE {table} ENABLE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE {table} FORCE ROW LEVEL SECURITY')
        op.execute(f"CREATE POLICY tenant_isolation ON {table} USING (current_setting('app.saas_system',true)='true' OR tenant_id=NULLIF(current_setting('app.tenant_id',true),'')::bigint) WITH CHECK (current_setting('app.saas_system',true)='true' OR tenant_id=NULLIF(current_setting('app.tenant_id',true),'')::bigint)")
    op.execute("DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='drapemind_runtime') THEN GRANT SELECT,INSERT,UPDATE,DELETE ON abastecimiento_pedidos,abastecimiento_items,offline_reservas_recibidas TO drapemind_runtime; GRANT USAGE,SELECT ON SEQUENCE abastecimiento_pedidos_id_seq,abastecimiento_items_id_seq,offline_reservas_recibidas_id_seq TO drapemind_runtime; END IF; END $$")


def downgrade():
    op.drop_table('offline_reservas_recibidas')
    op.drop_table('abastecimiento_items')
    op.drop_table('abastecimiento_pedidos')
