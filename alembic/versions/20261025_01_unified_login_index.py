"""Indexed email lookup for automatic account resolution, preserving tenant-scoped uniqueness."""
from alembic import op
import sqlalchemy as sa

revision='20261025_01'
down_revision='20261018_01'
branch_labels=depends_on=None


def upgrade():
    op.create_index('ix_usuarios_login_email','usuarios',[sa.text('lower(email)')])


def downgrade():
    op.drop_index('ix_usuarios_login_email',table_name='usuarios')
