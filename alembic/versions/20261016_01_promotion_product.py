"""Add the product relation already used by promotion endpoints.

Revision ID: 20261016_01
Revises: 20261015_02
"""

from alembic import op

revision = "20261016_01"
down_revision = "20261015_02"
branch_labels = None
depends_on = None


def upgrade():
    # Safe for databases that received the column manually before this migration.
    op.execute(
        "ALTER TABLE promociones ADD COLUMN IF NOT EXISTS producto_id BIGINT REFERENCES productos(id) ON DELETE SET NULL"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_promociones_producto_id ON promociones (producto_id)"
    )


def downgrade():
    op.execute("DROP INDEX IF EXISTS ix_promociones_producto_id")
    op.execute("ALTER TABLE promociones DROP COLUMN IF EXISTS producto_id")
