"""Agregar tabla proveedor_suministros para catalogo de lotes e insumos de proveedores (CU-33)

Revision ID: 20260918_02
Revises: 20260918_01
Create Date: 2026-09-18 10:30:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = "20260918_02"
down_revision = "20260918_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "proveedor_suministros",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), primary_key=True),
        sa.Column("proveedor_id", sa.BigInteger(), sa.ForeignKey("proveedores.id", ondelete="CASCADE"), nullable=False),
        sa.Column("nombre_suministro", sa.String(150), nullable=False),
        sa.Column("sku_proveedor", sa.String(60), nullable=True),
        sa.Column("categoria", sa.String(100), server_default="Telas y Confección", nullable=False),
        sa.Column("unidad_medida", sa.String(30), server_default="Metros", nullable=False),
        sa.Column("costo_unitario", sa.Numeric(10, 2), nullable=False),
        sa.Column("cantidad_disponible", sa.Integer(), server_default="0", nullable=False),
        sa.Column("tiempo_entrega_dias", sa.Integer(), server_default="5", nullable=False),
        sa.Column("estado", sa.String(30), server_default="DISPONIBLE", nullable=False),
        sa.Column("activo", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_proveedor_suministros_proveedor_id", "proveedor_suministros", ["proveedor_id"])
    op.create_index("ix_proveedor_suministros_categoria", "proveedor_suministros", ["categoria"])


def downgrade() -> None:
    op.drop_index("ix_proveedor_suministros_categoria", table_name="proveedor_suministros")
    op.drop_index("ix_proveedor_suministros_proveedor_id", table_name="proveedor_suministros")
    op.drop_table("proveedor_suministros")
