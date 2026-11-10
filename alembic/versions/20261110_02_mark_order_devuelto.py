"""Revisión histórica reservada; no modifica transacciones comerciales."""

revision = '20261110_02'
down_revision = '20261110_01'
branch_labels = None
depends_on = None


def upgrade():
    # Financial changes belong to tenant-scoped application operations and Stripe.
    # A schema upgrade must never mark a hard-coded order or its payments refunded.
    pass


def downgrade():
    pass
