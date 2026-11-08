"""Roles propios de empresa y dispositivos de una identidad multitienda."""
from alembic import op
revision='20261108_01'
down_revision='20261104_01'
branch_labels=None
depends_on=None

def upgrade():
    op.execute('\nCREATE TABLE roles_empresa (\n\tid BIGSERIAL NOT NULL, \n\tnombre VARCHAR(80) NOT NULL, \n\tdescripcion VARCHAR(300), \n\tbase_role rol_usuario NOT NULL, \n\tpermisos JSONB NOT NULL, \n\tactivo BOOLEAN NOT NULL, \n\ttenant_id BIGINT NOT NULL, \n\tPRIMARY KEY (id), \n\tCONSTRAINT uq_role_company_name UNIQUE (tenant_id, nombre), \n\tFOREIGN KEY(tenant_id) REFERENCES saas_tenants (id) ON DELETE RESTRICT, \n\tCONSTRAINT uq_roles_empresa_id_tenant UNIQUE (id, tenant_id)\n)\n\n')
    op.execute('CREATE INDEX ix_roles_empresa_tenant_id ON roles_empresa (tenant_id)')
    op.execute('ALTER TABLE roles_empresa ENABLE ROW LEVEL SECURITY')
    op.execute('ALTER TABLE roles_empresa FORCE ROW LEVEL SECURITY')
    op.execute("CREATE POLICY tenant_isolation ON roles_empresa USING (current_setting('app.saas_system',true)='true' OR tenant_id=NULLIF(current_setting('app.tenant_id',true),'')::bigint) WITH CHECK (current_setting('app.saas_system',true)='true' OR tenant_id=NULLIF(current_setting('app.tenant_id',true),'')::bigint)")
    op.execute('\nCREATE TABLE accesos_usuario (\n\tid BIGSERIAL NOT NULL, \n\tusuario_id BIGINT NOT NULL, \n\trol_empresa_id BIGINT, \n\toverrides JSONB NOT NULL, \n\tupdated_by BIGINT NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\ttenant_id BIGINT NOT NULL, \n\tPRIMARY KEY (id), \n\tCONSTRAINT uq_access_company_user UNIQUE (tenant_id, usuario_id), \n\tFOREIGN KEY(tenant_id) REFERENCES saas_tenants (id) ON DELETE RESTRICT, \n\tCONSTRAINT uq_accesos_usuario_id_tenant UNIQUE (id, tenant_id), \n\tCONSTRAINT fk_accesos_usuario_updated_by_tenant FOREIGN KEY(updated_by, tenant_id) REFERENCES usuarios (id, tenant_id) ON DELETE RESTRICT, \n\tCONSTRAINT fk_accesos_usuario_usuario_id_tenant FOREIGN KEY(usuario_id, tenant_id) REFERENCES usuarios (id, tenant_id) ON DELETE CASCADE, \n\tCONSTRAINT fk_accesos_usuario_rol_empresa_id_tenant FOREIGN KEY(rol_empresa_id, tenant_id) REFERENCES roles_empresa (id, tenant_id) ON DELETE RESTRICT\n)\n\n')
    op.execute('CREATE INDEX ix_accesos_usuario_tenant_id ON accesos_usuario (tenant_id)')
    op.execute('ALTER TABLE accesos_usuario ENABLE ROW LEVEL SECURITY')
    op.execute('ALTER TABLE accesos_usuario FORCE ROW LEVEL SECURITY')
    op.execute("CREATE POLICY tenant_isolation ON accesos_usuario USING (current_setting('app.saas_system',true)='true' OR tenant_id=NULLIF(current_setting('app.tenant_id',true),'')::bigint) WITH CHECK (current_setting('app.saas_system',true)='true' OR tenant_id=NULLIF(current_setting('app.tenant_id',true),'')::bigint)")
    op.execute('ALTER TABLE dispositivos_usuario ADD COLUMN web_subscription JSONB')
    op.execute('DROP INDEX ix_dispositivos_usuario_token')
    op.execute('CREATE INDEX ix_dispositivos_usuario_token ON dispositivos_usuario (token)')

def downgrade():
    op.execute("DO $$ BEGIN IF EXISTS (SELECT token FROM dispositivos_usuario GROUP BY token HAVING count(*)>1) THEN RAISE EXCEPTION 'No es posible restaurar tokens únicos mientras existan dispositivos multitienda'; END IF; END $$")
    op.execute('DROP INDEX ix_dispositivos_usuario_token')
    op.execute('CREATE UNIQUE INDEX ix_dispositivos_usuario_token ON dispositivos_usuario (token)')
    op.execute('ALTER TABLE dispositivos_usuario DROP COLUMN web_subscription')
    op.drop_table('accesos_usuario')
    op.drop_table('roles_empresa')
