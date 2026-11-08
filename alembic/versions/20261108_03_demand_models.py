"""CU-28: entrenamiento persistente de demanda aislado por empresa."""
from alembic import op
revision='20261108_03'
down_revision='20261108_02'
branch_labels=None
depends_on=None

def upgrade():
    op.execute('\nCREATE TABLE modelos_demanda (\n\tid BIGSERIAL NOT NULL, \n\talcance VARCHAR(80) NOT NULL, \n\tsucursal_id BIGINT, \n\tentrenado_por BIGINT NOT NULL, \n\tdatos_hash VARCHAR(64) NOT NULL, \n\tmodelo VARCHAR(80) NOT NULL, \n\tartefacto JSONB NOT NULL, \n\tresultado JSONB NOT NULL, \n\tentrenado_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\ttenant_id BIGINT NOT NULL, \n\tPRIMARY KEY (id), \n\tCONSTRAINT uq_modelo_demanda_alcance UNIQUE (tenant_id, alcance), \n\tFOREIGN KEY(tenant_id) REFERENCES saas_tenants (id) ON DELETE RESTRICT, \n\tCONSTRAINT uq_modelos_demanda_id_tenant UNIQUE (id, tenant_id), \n\tCONSTRAINT fk_modelos_demanda_entrenado_por_tenant FOREIGN KEY(entrenado_por, tenant_id) REFERENCES usuarios (id, tenant_id) ON DELETE RESTRICT, \n\tCONSTRAINT fk_modelos_demanda_sucursal_id_tenant FOREIGN KEY(sucursal_id, tenant_id) REFERENCES sucursales (id, tenant_id) ON DELETE RESTRICT\n)\n\n')
    op.execute('CREATE INDEX ix_modelos_demanda_tenant_id ON modelos_demanda (tenant_id)')
    op.execute('ALTER TABLE modelos_demanda ENABLE ROW LEVEL SECURITY')
    op.execute('ALTER TABLE modelos_demanda FORCE ROW LEVEL SECURITY')
    op.execute("CREATE POLICY tenant_isolation ON modelos_demanda USING (current_setting('app.saas_system',true)='true' OR tenant_id=NULLIF(current_setting('app.tenant_id',true),'')::bigint) WITH CHECK (current_setting('app.saas_system',true)='true' OR tenant_id=NULLIF(current_setting('app.tenant_id',true),'')::bigint)")

def downgrade():
    op.drop_table('modelos_demanda')
