"""Remove the implicit model default; every interaction records its real configured model."""

from alembic import op
import sqlalchemy as sa

revision = "20261015_01"
down_revision = "20260920_03"
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column(
        "ai_interacciones", "modelo", existing_type=sa.String(80), server_default=None
    )


def downgrade():
    op.alter_column(
        "ai_interacciones",
        "modelo",
        existing_type=sa.String(80),
        server_default=sa.text("'NVIDIA'"),
    )
