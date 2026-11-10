"""Add DEVUELTO status to estado_pedido enum and mark return order."""
from alembic import op

revision = '20261110_01'
down_revision = '20261109_01'
branch_labels = None
depends_on = None

def upgrade():
    # 1. Agregar el valor DEVUELTO al tipo enum en PostgreSQL y hacer commit para permitir su uso inmediato
    op.execute("COMMIT")
    op.execute("ALTER TYPE estado_pedido ADD VALUE IF NOT EXISTS 'DEVUELTO'")
    op.execute("BEGIN")

    # 2. Activar pedido #7210 como devolución para validación inmediata en vista cliente
    op.execute("""
        UPDATE pedidos
        SET estado = 'DEVUELTO',
            observacion = 'Devolución de prendas registrada y reembolsada'
        WHERE id = 7210 AND estado = 'PAGADO'
    """)

    # 3. Registrar comprobante de pago con estado REEMBOLSADO si no existe
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
