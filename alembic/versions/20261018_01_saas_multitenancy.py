"""Shared PostgreSQL tenancy, subscriptions, composite ownership and RLS.

Existing records are retained in the legacy company; no catalog/customer duplication.
"""
from alembic import op
import sqlalchemy as sa

revision = '20261018_01'
down_revision = '20261016_01'
branch_labels = depends_on = None

OWNED = ('categorias','ciudades','temporadas_colecciones','usuarios','ai_sesiones','carritos','direcciones','dispositivos_usuario','notificaciones','perfiles_estilo_usuario','productos','proveedores','sucursales','ai_interacciones','favoritos','personal_sucursal','promociones','proveedor_suministros','reservas','variantes_producto','ai_recomendaciones','items_carrito','items_reserva','movimientos_inventario','pedidos','stock_sucursal','items_pedido','pagos')


def upgrade():
    connection = op.get_bind()
    op.execute("""CREATE TABLE saas_tenants (
        id BIGSERIAL PRIMARY KEY, name VARCHAR(150) NOT NULL, slug VARCHAR(80) NOT NULL UNIQUE,
        active BOOLEAN NOT NULL DEFAULT true, is_demo BOOLEAN NOT NULL DEFAULT false,
        admin_user_id BIGINT REFERENCES usuarios(id), stripe_customer_id VARCHAR(100) UNIQUE,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now())""")
    op.execute("""CREATE TABLE saas_plans (
        id BIGSERIAL PRIMARY KEY, code VARCHAR(30) NOT NULL UNIQUE, name VARCHAR(80) NOT NULL,
        max_branches INTEGER NOT NULL CHECK(max_branches>0), products_sales BOOLEAN NOT NULL DEFAULT true,
        reservations BOOLEAN NOT NULL DEFAULT true, offline BOOLEAN NOT NULL DEFAULT true,
        reports BOOLEAN NOT NULL DEFAULT true, ai_reports BOOLEAN NOT NULL DEFAULT false,
        stripe_price_id VARCHAR(100) UNIQUE, stripe_product_id VARCHAR(100), stripe_annual_price_id VARCHAR(100) UNIQUE,
        monthly_amount_minor INTEGER NOT NULL DEFAULT 9900, annual_amount_minor INTEGER NOT NULL DEFAULT 99000,
        currency VARCHAR(3) NOT NULL DEFAULT 'bob', active BOOLEAN NOT NULL DEFAULT true)""")
    op.execute('CREATE TABLE saas_prices(id VARCHAR(100) PRIMARY KEY, plan_id BIGINT NOT NULL REFERENCES saas_plans(id))')
    op.execute("""CREATE TABLE saas_subscriptions (
        id BIGSERIAL PRIMARY KEY, tenant_id BIGINT NOT NULL UNIQUE REFERENCES saas_tenants(id),
        plan_id BIGINT NOT NULL REFERENCES saas_plans(id), status VARCHAR(30) NOT NULL DEFAULT 'PENDING',
        starts_at TIMESTAMPTZ, ends_at TIMESTAMPTZ, source VARCHAR(30) NOT NULL DEFAULT 'STRIPE',
        stripe_subscription_id VARCHAR(100) UNIQUE, cancel_at_period_end BOOLEAN NOT NULL DEFAULT false,
        CONSTRAINT ck_subscription_state CHECK(status IN ('PENDING','ACTIVE','TRIALING','PAST_DUE','CANCELED','UNPAID','SUSPENDED','EXPIRED','LIMIT_EXCEEDED')))""")
    op.execute("""CREATE TABLE saas_billing_events (id VARCHAR(120) PRIMARY KEY, event_type VARCHAR(100) NOT NULL,
        tenant_id BIGINT REFERENCES saas_tenants(id), created_at TIMESTAMPTZ NOT NULL DEFAULT now())""")
    op.execute("""CREATE TABLE saas_checkout_attempts (id VARCHAR(36) PRIMARY KEY,
        tenant_id BIGINT NOT NULL REFERENCES saas_tenants(id), plan_id BIGINT NOT NULL REFERENCES saas_plans(id),
        stripe_session_id VARCHAR(120) UNIQUE, billing_interval VARCHAR(10) NOT NULL DEFAULT 'month', created_at TIMESTAMPTZ NOT NULL DEFAULT now())""")
    op.execute("INSERT INTO saas_plans(code,name,max_branches,ai_reports) VALUES ('BASIC','Básico',2,false),('PRO','Profesional',10,true)")
    op.execute("UPDATE saas_plans SET monthly_amount_minor=24900,annual_amount_minor=249000 WHERE code='PRO'")
    op.execute("INSERT INTO saas_tenants(id,name,slug) VALUES(1,'DrapeMind','drapemind')")
    op.execute("SELECT setval(pg_get_serial_sequence('saas_tenants','id'),1,true)")
    op.execute("INSERT INTO saas_subscriptions(tenant_id,plan_id,status,starts_at,ends_at,source) SELECT 1,id,'ACTIVE',now(),now()+interval '365 days','LEGACY' FROM saas_plans WHERE code='PRO'")
    for table in OWNED:
        op.add_column(table, sa.Column('tenant_id', sa.BigInteger(), nullable=True))
        op.execute(sa.text(f'UPDATE {table} SET tenant_id=1'))
        if table != 'usuarios': op.alter_column(table, 'tenant_id', nullable=False)
        op.create_index(f'ix_{table}_tenant_id', table, ['tenant_id'])
        op.create_foreign_key(f'fk_{table}_tenant', table, 'saas_tenants', ['tenant_id'], ['id'], ondelete='RESTRICT')
        op.create_unique_constraint(f'uq_{table}_id_tenant', table, ['id','tenant_id'])
    op.add_column('usuarios', sa.Column('is_platform_admin', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.create_check_constraint('ck_user_has_company', 'usuarios', 'tenant_id IS NOT NULL OR is_platform_admin')
    op.execute("UPDATE saas_tenants SET admin_user_id=(SELECT id FROM usuarios WHERE rol='ADMIN' AND tenant_id=1 ORDER BY id LIMIT 1) WHERE id=1")
    op.create_index('uq_platform_email','usuarios',['email'],unique=True,postgresql_where=sa.text('tenant_id IS NULL'))
    op.drop_constraint('uq_ciudad_nombre_departamento','ciudades',type_='unique')
    op.create_unique_constraint('uq_ciudad_nombre_departamento','ciudades',['tenant_id','nombre','departamento'])
    scoped_uniques = {'usuarios':('email',),'categorias':('slug',),'sucursales':('codigo',),'variantes_producto':('sku','codigo_barras'),'promociones':('codigo',),'temporadas_colecciones':('codigo',)}
    inspector = sa.inspect(connection)
    for table, fields in scoped_uniques.items():
        for constraint in inspector.get_unique_constraints(table):
            if tuple(constraint['column_names']) in [(field,) for field in fields]: op.drop_constraint(constraint['name'],table,type_='unique')
        for index in inspector.get_indexes(table):
            if index.get('unique') and tuple(index['column_names']) in [(field,) for field in fields] and not index.get('duplicates_constraint'): op.drop_index(index['name'],table_name=table)
        for field in fields: op.create_unique_constraint(f'uq_{table}_tenant_{field}',table,['tenant_id',field])
    for table in OWNED:
        for fk in inspector.get_foreign_keys(table):
            if fk['referred_table'] in OWNED and len(fk['constrained_columns']) == 1:
                column = fk['constrained_columns'][0]
                op.create_foreign_key(f'fk_{table}_{column}_tenant',table,fk['referred_table'],[column,'tenant_id'],[fk['referred_columns'][0],'tenant_id'])
        op.execute(sa.text(f'ALTER TABLE {table} ENABLE ROW LEVEL SECURITY'))
        op.execute(sa.text(f'ALTER TABLE {table} FORCE ROW LEVEL SECURITY'))
        op.execute(sa.text(f"CREATE POLICY tenant_isolation ON {table} USING (tenant_id=NULLIF(current_setting('app.tenant_id',true),'')::bigint OR current_setting('app.saas_system',true)='true') WITH CHECK (tenant_id=NULLIF(current_setting('app.tenant_id',true),'')::bigint OR current_setting('app.saas_system',true)='true')"))
    op.execute("""CREATE FUNCTION saas_check_branch_limit() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE maximum integer; current_count integer;
    BEGIN
      IF NOT NEW.activo THEN RETURN NEW; END IF;
      IF TG_OP='UPDATE' AND OLD.activo AND OLD.tenant_id=NEW.tenant_id THEN RETURN NEW; END IF;
      PERFORM 1 FROM saas_tenants WHERE id=NEW.tenant_id FOR UPDATE;
      SELECT p.max_branches INTO maximum FROM saas_subscriptions s JOIN saas_plans p ON p.id=s.plan_id
        WHERE s.tenant_id=NEW.tenant_id AND s.status IN ('ACTIVE','TRIALING') AND s.starts_at<=now() AND s.ends_at>now();
      IF maximum IS NULL THEN RAISE EXCEPTION 'SUBSCRIPTION_REQUIRED'; END IF;
      SELECT count(*) INTO current_count FROM sucursales WHERE tenant_id=NEW.tenant_id AND activo AND id<>COALESCE(NEW.id,0);
      IF current_count>=maximum THEN RAISE EXCEPTION 'BRANCH_LIMIT'; END IF;
      RETURN NEW;
    END $$""")
    op.execute('CREATE TRIGGER saas_branch_limit BEFORE INSERT OR UPDATE OF activo,tenant_id ON sucursales FOR EACH ROW EXECUTE FUNCTION saas_check_branch_limit()')
    for view in inspector.get_view_names():
        op.execute(sa.text(f'ALTER VIEW "{view}" SET (security_invoker=true)'))


def downgrade():
    raise RuntimeError('La reversión automática eliminaría el aislamiento empresarial. Restaura el respaldo previo en una base separada para revisar la reversión.')
