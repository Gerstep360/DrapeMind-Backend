"""CU-20: distinguir reembolsos pendientes y fallidos de los confirmados."""
from alembic import op
import sqlalchemy as sa

revision = '20261110_03'
down_revision = '20261110_02'
branch_labels = None
depends_on = None


def upgrade():
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE estado_pago ADD VALUE IF NOT EXISTS 'REEMBOLSO_PENDIENTE'")
        op.execute("ALTER TYPE estado_pago ADD VALUE IF NOT EXISTS 'REEMBOLSO_FALLIDO'")
    for constraint in sa.inspect(op.get_bind()).get_unique_constraints('cambios_prendas'):
        if constraint['column_names'] in (['pedido_nuevo_id'], ['tenant_id', 'pedido_nuevo_id'], ['pedido_nuevo_id','tenant_id']):
            op.drop_constraint(constraint['name'], 'cambios_prendas', type_='unique')


def downgrade():
    # PostgreSQL cannot safely remove enum values while retaining historical payments.
    pass
