"""Vincular cuenta de usuario y agregar rol PROVEEDOR para proveedores (CU-33)

Revision ID: 20260920_03
Revises: 20260918_02
Create Date: 2026-09-20 18:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = "20260920_03"
down_revision = "20260918_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Agregar valor PROVEEDOR al enum rol_usuario si no existe
    op.execute("ALTER TYPE rol_usuario ADD VALUE IF NOT EXISTS 'PROVEEDOR'")

    # 2. Agregar columna usuario_id a proveedores
    op.add_column(
        "proveedores",
        sa.Column(
            "usuario_id",
            sa.BigInteger(),
            sa.ForeignKey("usuarios.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_proveedores_usuario_id", "proveedores", ["usuario_id"])


def downgrade() -> None:
    op.drop_index("ix_proveedores_usuario_id", table_name="proveedores")
    op.drop_column("proveedores", "usuario_id")
