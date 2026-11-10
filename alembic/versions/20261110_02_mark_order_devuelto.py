"""Mark order 7210 as DEVUELTO and insert refund payment."""
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
        WHERE id = 7210 AND estado = 'PAGADO'
    """)

    op.execute("""
        INSERT INTO pagos (
            tenant_id, pedido_id, metodo, proveedor, monto, moneda, estado,
            referencia_externa, paid_at, created_at
        )
        VALUES (
            4, 7210, 'EFECTIVO', 'CAMBIO_DEVOLUCION', 38.90, 'BOB', 'REEMBOLSADO',
            'REFUND-7210-DEVOLUCION', now(), now()
        )
        ON CONFLICT (referencia_externa) DO NOTHING
    """)

def downgrade():
    op.execute("""
        UPDATE pedidos
        SET estado = 'PAGADO'
        WHERE id = 7210 AND estado = 'DEVUELTO'
    """)
