"""CU-22/23: tarjetas tokenizadas y compras diferidas recuperables."""
from alembic import op
revision='20261108_02'
down_revision='20261108_01'
branch_labels=None
depends_on=None

def upgrade():
    op.execute('ALTER TABLE usuarios ADD COLUMN stripe_customer_id VARCHAR(100)')
    op.execute('ALTER TABLE usuarios ADD CONSTRAINT uq_usuarios_stripe_customer_id UNIQUE (stripe_customer_id)')
    op.execute('\nCREATE TABLE tarjetas_guardadas (\n\tid BIGSERIAL NOT NULL, \n\tusuario_id BIGINT NOT NULL, \n\tstripe_payment_method VARCHAR(100) NOT NULL, \n\tsetup_intent VARCHAR(100) NOT NULL, \n\tmarca VARCHAR(30) NOT NULL, \n\tultimos_cuatro VARCHAR(4) NOT NULL, \n\tmes_vencimiento INTEGER NOT NULL, \n\tanio_vencimiento INTEGER NOT NULL, \n\tactivo BOOLEAN NOT NULL, \n\tconsentimiento_version VARCHAR(30) NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\ttenant_id BIGINT NOT NULL, \n\tPRIMARY KEY (id), \n\tCONSTRAINT uq_saved_card_owner_method UNIQUE (tenant_id, usuario_id, stripe_payment_method), \n\tFOREIGN KEY(tenant_id) REFERENCES saas_tenants (id) ON DELETE RESTRICT, \n\tCONSTRAINT uq_tarjetas_guardadas_id_tenant UNIQUE (id, tenant_id), \n\tCONSTRAINT fk_tarjetas_guardadas_usuario_id_tenant FOREIGN KEY(usuario_id, tenant_id) REFERENCES usuarios (id, tenant_id) ON DELETE RESTRICT\n)\n\n')
    op.execute('CREATE INDEX ix_tarjetas_guardadas_tenant_id ON tarjetas_guardadas (tenant_id)')
    op.execute('ALTER TABLE tarjetas_guardadas ENABLE ROW LEVEL SECURITY')
    op.execute('ALTER TABLE tarjetas_guardadas FORCE ROW LEVEL SECURITY')
    op.execute("CREATE POLICY tenant_isolation ON tarjetas_guardadas USING (current_setting('app.saas_system',true)='true' OR tenant_id=NULLIF(current_setting('app.tenant_id',true),'')::bigint) WITH CHECK (current_setting('app.saas_system',true)='true' OR tenant_id=NULLIF(current_setting('app.tenant_id',true),'')::bigint)")
    op.execute('\nCREATE TABLE compras_diferidas (\n\tid BIGSERIAL NOT NULL, \n\tusuario_id BIGINT NOT NULL, \n\toperacion_id VARCHAR(36) NOT NULL, \n\tpayload_hash VARCHAR(64) NOT NULL, \n\tpayload JSONB NOT NULL, \n\ttarjeta_id BIGINT, \n\tpedido_id BIGINT, \n\testado VARCHAR(40) NOT NULL, \n\ttotal_autorizado NUMERIC(10, 2) NOT NULL, \n\tconsentimiento_at TIMESTAMP WITH TIME ZONE, \n\tvence_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tmensaje VARCHAR(500), \n\tintentos INTEGER NOT NULL, \n\tsiguiente_intento TIMESTAMP WITH TIME ZONE, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\ttenant_id BIGINT NOT NULL, \n\tPRIMARY KEY (id), \n\tCONSTRAINT uq_deferred_purchase_owner_operation UNIQUE (tenant_id, usuario_id, operacion_id), \n\tFOREIGN KEY(tenant_id) REFERENCES saas_tenants (id) ON DELETE RESTRICT, \n\tCONSTRAINT uq_compras_diferidas_id_tenant UNIQUE (id, tenant_id), \n\tCONSTRAINT fk_compras_diferidas_pedido_id_tenant FOREIGN KEY(pedido_id, tenant_id) REFERENCES pedidos (id, tenant_id) ON DELETE RESTRICT, \n\tCONSTRAINT fk_compras_diferidas_tarjeta_id_tenant FOREIGN KEY(tarjeta_id, tenant_id) REFERENCES tarjetas_guardadas (id, tenant_id) ON DELETE RESTRICT, \n\tCONSTRAINT fk_compras_diferidas_usuario_id_tenant FOREIGN KEY(usuario_id, tenant_id) REFERENCES usuarios (id, tenant_id) ON DELETE RESTRICT\n)\n\n')
    op.execute('CREATE INDEX ix_compras_diferidas_estado ON compras_diferidas (estado)')
    op.execute('CREATE INDEX ix_compras_diferidas_tenant_id ON compras_diferidas (tenant_id)')
    op.execute('ALTER TABLE compras_diferidas ENABLE ROW LEVEL SECURITY')
    op.execute('ALTER TABLE compras_diferidas FORCE ROW LEVEL SECURITY')
    op.execute("CREATE POLICY tenant_isolation ON compras_diferidas USING (current_setting('app.saas_system',true)='true' OR tenant_id=NULLIF(current_setting('app.tenant_id',true),'')::bigint) WITH CHECK (current_setting('app.saas_system',true)='true' OR tenant_id=NULLIF(current_setting('app.tenant_id',true),'')::bigint)")

def downgrade():
    connection=op.get_bind()
    connection.exec_driver_sql("SELECT set_config('app.saas_system','true',true)")
    if connection.exec_driver_sql('SELECT count(*) FROM compras_diferidas').scalar():
        raise RuntimeError('Conserva y concilia las compras diferidas antes de revertir esta migración')
    op.drop_table('compras_diferidas')
    op.drop_table('tarjetas_guardadas')
    op.execute('ALTER TABLE usuarios DROP CONSTRAINT uq_usuarios_stripe_customer_id')
    op.execute('ALTER TABLE usuarios DROP COLUMN stripe_customer_id')
