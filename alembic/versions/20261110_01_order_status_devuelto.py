"""Add DEVUELTO status to estado_pedido enum."""
from alembic import op

revision = '20261110_01'
down_revision = '20261109_01'
branch_labels = None
depends_on = None

def upgrade():
    op.execute("ALTER TYPE estado_pedido ADD VALUE IF NOT EXISTS 'DEVUELTO'")

def downgrade():
    pass
