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

    # 2. Agregar columna usuario_id de manera idempotente
    op.execute("ALTER TABLE proveedores ADD COLUMN IF NOT EXISTS usuario_id BIGINT REFERENCES usuarios(id) ON DELETE SET NULL")

    # 3. Crear indice de manera idempotente
    op.execute("CREATE INDEX IF NOT EXISTS ix_proveedores_usuario_id ON proveedores(usuario_id)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_proveedores_usuario_id")
    op.execute("ALTER TABLE proveedores DROP COLUMN IF EXISTS usuario_id")
