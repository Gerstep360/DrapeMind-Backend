"""CU-30: reseñas de prendas y aislamiento multitenant."""
from alembic import op
revision='20261109_01'
down_revision='20261108_03'
branch_labels=None
depends_on=None

def upgrade():
    op.execute('\nCREATE TABLE resenas_prendas (\n\tid BIGSERIAL NOT NULL, \n\tproducto_id BIGINT NOT NULL, \n\tusuario_id BIGINT NOT NULL, \n\tcalificacion SMALLINT NOT NULL, \n\ttitulo VARCHAR(120), \n\tcomentario TEXT NOT NULL, \n\tcompra_verificada BOOLEAN NOT NULL, \n\tactivo BOOLEAN NOT NULL, \n\ttenant_id BIGINT NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tPRIMARY KEY (id), \n\tCONSTRAINT uq_resena_tenant_producto_usuario UNIQUE (tenant_id, producto_id, usuario_id), \n\tCONSTRAINT ck_resena_calificacion CHECK (calificacion BETWEEN 1 AND 5), \n\tCONSTRAINT ck_resena_comentario CHECK (length(trim(comentario)) BETWEEN 3 AND 1000), \n\tFOREIGN KEY(tenant_id) REFERENCES saas_tenants (id) ON DELETE RESTRICT, \n\tCONSTRAINT uq_resenas_prendas_id_tenant UNIQUE (id, tenant_id), \n\tCONSTRAINT fk_resenas_prendas_usuario_id_tenant FOREIGN KEY(usuario_id, tenant_id) REFERENCES usuarios (id, tenant_id) ON DELETE CASCADE, \n\tCONSTRAINT fk_resenas_prendas_producto_id_tenant FOREIGN KEY(producto_id, tenant_id) REFERENCES productos (id, tenant_id) ON DELETE CASCADE\n)\n\n')
    op.execute('CREATE INDEX ix_resenas_prendas_tenant_id ON resenas_prendas (tenant_id)')
    op.execute('CREATE INDEX ix_resena_producto_calificacion ON resenas_prendas (producto_id, calificacion)')
    op.execute('CREATE INDEX ix_resena_tenant_producto_activo ON resenas_prendas (tenant_id, producto_id, activo)')
    op.execute('CREATE INDEX ix_resenas_prendas_usuario_id ON resenas_prendas (usuario_id)')
    op.execute('CREATE INDEX ix_resenas_prendas_producto_id ON resenas_prendas (producto_id)')
    op.execute('ALTER TABLE resenas_prendas ENABLE ROW LEVEL SECURITY')
    op.execute('ALTER TABLE resenas_prendas FORCE ROW LEVEL SECURITY')
    op.execute("CREATE POLICY tenant_isolation ON resenas_prendas USING (current_setting('app.saas_system',true)='true' OR tenant_id=NULLIF(current_setting('app.tenant_id',true),'')::bigint) WITH CHECK (current_setting('app.saas_system',true)='true' OR tenant_id=NULLIF(current_setting('app.tenant_id',true),'')::bigint)")

def downgrade():
    op.drop_table('resenas_prendas')
