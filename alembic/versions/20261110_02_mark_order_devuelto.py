"""Mark order 7210 as DEVUELTO and set payment to REEMBOLSADO."""
from alembic import op

revision = '20261110_02'
down_revision = '20261110_01'
branch_labels = None
depends_on = None

def upgrade():
    op.execute("""
        UPDATE pedidos
        SET estado = 'DEVUELTO',
            observacion = 'Devolución de prendas registrada y reembolsada'
        WHERE id = 7210;
    """)

    op.execute("""
        UPDATE pagos
        SET estado = 'REEMBOLSADO'
        WHERE pedido_id = 7210;
    """)

def downgrade():
    op.execute("""
        UPDATE pedidos
        SET estado = 'PAGADO'
        WHERE id = 7210 AND estado = 'DEVUELTO';
    """)
    op.execute("""
        UPDATE pagos
        SET estado = 'APROBADO'
        WHERE pedido_id = 7210 AND estado = 'REEMBOLSADO';
    """)
