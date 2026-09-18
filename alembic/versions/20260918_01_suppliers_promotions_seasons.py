"""Agregar tablas para proveedores, promociones y temporadas_colecciones

Revision ID: 20260918_01
Revises: 20260912_01
Create Date: 2026-09-18 10:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = "20260918_01"
down_revision = "20260912_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Tabla proveedores (CU-32)
    op.create_table(
        "proveedores",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), primary_key=True),
        sa.Column("nombre_empresa", sa.String(150), nullable=False),
        sa.Column("nit", sa.String(50), nullable=True),
        sa.Column("contacto_nombre", sa.String(120), nullable=True),
        sa.Column("telefono", sa.String(50), nullable=True),
        sa.Column("email", sa.String(150), nullable=True),
        sa.Column("ciudad", sa.String(100), server_default="La Paz", nullable=False),
        sa.Column("direccion", sa.String(250), nullable=True),
        sa.Column("categoria_suministro", sa.String(100), server_default="Telas y Confección", nullable=False),
        sa.Column("activo", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_proveedores_nombre", "proveedores", ["nombre_empresa"])

    # 2. Tabla promociones (CU-36)
    op.create_table(
        "promociones",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), primary_key=True),
        sa.Column("codigo", sa.String(50), nullable=False, unique=True),
        sa.Column("descripcion", sa.String(255), nullable=True),
        sa.Column("tipo_descuento", sa.String(20), server_default="PORCENTAJE", nullable=False),
        sa.Column("valor_descuento", sa.Numeric(10, 2), nullable=False),
        sa.Column("monto_minimo_compra", sa.Numeric(10, 2), server_default="0.00", nullable=False),
        sa.Column("fecha_inicio", sa.DateTime(timezone=True), nullable=True),
        sa.Column("fecha_fin", sa.DateTime(timezone=True), nullable=True),
        sa.Column("limite_usos", sa.Integer(), nullable=True),
        sa.Column("usos_actuales", sa.Integer(), server_default="0", nullable=False),
        sa.Column("activo", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_promociones_codigo", "promociones", ["codigo"])

    # 3. Tabla temporadas_colecciones (CU-31)
    op.create_table(
        "temporadas_colecciones",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), primary_key=True),
        sa.Column("nombre", sa.String(120), nullable=False),
        sa.Column("codigo", sa.String(50), nullable=False, unique=True),
        sa.Column("descripcion", sa.Text(), nullable=True),
        sa.Column("fecha_inicio", sa.DateTime(timezone=True), nullable=True),
        sa.Column("fecha_fin", sa.DateTime(timezone=True), nullable=True),
        sa.Column("activo", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_temporadas_colecciones_codigo", "temporadas_colecciones", ["codigo"])


def downgrade() -> None:
    op.drop_index("ix_temporadas_colecciones_codigo", table_name="temporadas_colecciones")
    op.drop_table("temporadas_colecciones")
    op.drop_index("ix_promociones_codigo", table_name="promociones")
    op.drop_table("promociones")
    op.drop_index("ix_proveedores_nombre", table_name="proveedores")
    op.drop_table("proveedores")
