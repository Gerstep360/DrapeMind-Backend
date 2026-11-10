"""Subscription invoice history and quantity promotion thresholds."""
from alembic import op
import sqlalchemy as sa
revision='20261110_04'
down_revision='20261110_03'
branch_labels=None
depends_on=None


def upgrade():
    op.add_column('promociones',sa.Column('cantidad_minima',sa.Integer(),server_default='1',nullable=False))
    op.create_check_constraint('ck_promotion_quantity','promociones','cantidad_minima >= 1 AND cantidad_minima <= 1000')
    op.create_table('saas_invoices',
        sa.Column('id',sa.String(120),primary_key=True),
        sa.Column('tenant_id',sa.BigInteger(),sa.ForeignKey('saas_tenants.id',ondelete='RESTRICT'),nullable=False),
        sa.Column('subscription_id',sa.String(120),nullable=False),sa.Column('number',sa.String(120)),sa.Column('plan_name',sa.String(160)),
        sa.Column('status',sa.String(25),nullable=False),sa.Column('currency',sa.String(3),nullable=False),
        sa.Column('amount_due_minor',sa.BigInteger(),nullable=False),sa.Column('amount_paid_minor',sa.BigInteger(),nullable=False),sa.Column('amount_remaining_minor',sa.BigInteger(),nullable=False),
        sa.Column('attempt_count',sa.Integer(),nullable=False),sa.Column('livemode',sa.Boolean(),nullable=False),
        sa.Column('hosted_url',sa.String(1500)),sa.Column('pdf_url',sa.String(1500)),
        sa.Column('issued_at',sa.DateTime(timezone=True),nullable=False),sa.Column('paid_at',sa.DateTime(timezone=True)),sa.Column('synced_at',sa.DateTime(timezone=True),server_default=sa.func.now(),nullable=False),
        sa.CheckConstraint('amount_due_minor >= 0 AND amount_paid_minor >= 0 AND amount_remaining_minor >= 0',name='ck_saas_invoice_amounts'))
    op.create_index('ix_saas_invoices_tenant_id','saas_invoices',['tenant_id'])
    op.create_index('ix_saas_invoices_issued_at','saas_invoices',['issued_at'])
    op.execute('ALTER TABLE saas_invoices ENABLE ROW LEVEL SECURITY')
    op.execute('ALTER TABLE saas_invoices FORCE ROW LEVEL SECURITY')
    op.execute("CREATE POLICY tenant_isolation ON saas_invoices USING (current_setting('app.saas_system',true)='true' OR tenant_id=NULLIF(current_setting('app.tenant_id',true),'')::bigint) WITH CHECK (current_setting('app.saas_system',true)='true' OR tenant_id=NULLIF(current_setting('app.tenant_id',true),'')::bigint)")


def downgrade():
    op.drop_table('saas_invoices')
    op.drop_constraint('ck_promotion_quantity','promociones',type_='check')
    op.drop_column('promociones','cantidad_minima')
