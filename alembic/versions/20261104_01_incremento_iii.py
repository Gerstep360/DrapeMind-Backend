"""Incremento III: confirmación recuperable y reportes empresariales."""
from alembic import op
revision='20261104_01'
down_revision='20261028_02'
branch_labels=None
depends_on=None

def upgrade():
    op.execute('\nCREATE TABLE checkout_confirmaciones (\n\tid BIGSERIAL NOT NULL, \n\tusuario_id BIGINT NOT NULL, \n\toperacion_id VARCHAR(36) NOT NULL, \n\tpayload_hash VARCHAR(64) NOT NULL, \n\tpedido_id BIGINT NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\ttenant_id BIGINT NOT NULL, \n\tPRIMARY KEY (id), \n\tCONSTRAINT uq_checkout_owner_operation UNIQUE (tenant_id, usuario_id, operacion_id), \n\tFOREIGN KEY(tenant_id) REFERENCES saas_tenants (id) ON DELETE RESTRICT, \n\tCONSTRAINT uq_checkout_confirmaciones_id_tenant UNIQUE (id, tenant_id), \n\tCONSTRAINT fk_checkout_confirmaciones_pedido_id_tenant FOREIGN KEY(pedido_id, tenant_id) REFERENCES pedidos (id, tenant_id), \n\tCONSTRAINT fk_checkout_confirmaciones_usuario_id_tenant FOREIGN KEY(usuario_id, tenant_id) REFERENCES usuarios (id, tenant_id)\n)\n\n')
    op.execute('CREATE INDEX ix_checkout_confirmaciones_tenant_id ON checkout_confirmaciones (tenant_id)')
    op.execute('ALTER TABLE checkout_confirmaciones ENABLE ROW LEVEL SECURITY')
    op.execute('ALTER TABLE checkout_confirmaciones FORCE ROW LEVEL SECURITY')
    op.execute("CREATE POLICY tenant_isolation ON checkout_confirmaciones USING (current_setting('app.saas_system',true)='true' OR tenant_id=NULLIF(current_setting('app.tenant_id',true),'')::bigint) WITH CHECK (current_setting('app.saas_system',true)='true' OR tenant_id=NULLIF(current_setting('app.tenant_id',true),'')::bigint)")
    op.execute('\nCREATE TABLE reportes_empresariales (\n\tid BIGSERIAL NOT NULL, \n\tusuario_id BIGINT NOT NULL, \n\tconsulta TEXT NOT NULL, \n\tentrada VARCHAR(10) NOT NULL, \n\tfiltros JSONB NOT NULL, \n\tresultado JSONB NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\ttenant_id BIGINT NOT NULL, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(tenant_id) REFERENCES saas_tenants (id) ON DELETE RESTRICT, \n\tCONSTRAINT uq_reportes_empresariales_id_tenant UNIQUE (id, tenant_id), \n\tCONSTRAINT fk_reportes_empresariales_usuario_id_tenant FOREIGN KEY(usuario_id, tenant_id) REFERENCES usuarios (id, tenant_id)\n)\n\n')
    op.execute('CREATE INDEX ix_reportes_empresariales_tenant_id ON reportes_empresariales (tenant_id)')
    op.execute('ALTER TABLE reportes_empresariales ENABLE ROW LEVEL SECURITY')
    op.execute('ALTER TABLE reportes_empresariales FORCE ROW LEVEL SECURITY')
    op.execute("CREATE POLICY tenant_isolation ON reportes_empresariales USING (current_setting('app.saas_system',true)='true' OR tenant_id=NULLIF(current_setting('app.tenant_id',true),'')::bigint) WITH CHECK (current_setting('app.saas_system',true)='true' OR tenant_id=NULLIF(current_setting('app.tenant_id',true),'')::bigint)")

def downgrade():
    op.drop_table('reportes_empresariales')
    op.drop_table('checkout_confirmaciones')
