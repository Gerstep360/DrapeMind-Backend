"""Agregar tabla perfiles_estilo_usuario para onboarding de estilo e inferencia IA

Revision ID: 20260912_01
Revises: 20260827_01
Create Date: 2026-09-12 11:00:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "20260912_01"
down_revision = "20260827_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "perfiles_estilo_usuario",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), primary_key=True),
        sa.Column("usuario_id", sa.BigInteger(), sa.ForeignKey("usuarios.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("genero", sa.String(30), nullable=True),
        sa.Column("estilos_preferidos", JSONB(astext_type=sa.Text()), server_default="[]", nullable=False),
        sa.Column("talla_superior", sa.String(20), nullable=True),
        sa.Column("talla_inferior", sa.String(20), nullable=True),
        sa.Column("talla_calzado", sa.String(20), nullable=True),
        sa.Column("colores_favoritos", JSONB(astext_type=sa.Text()), server_default="[]", nullable=False),
        sa.Column("ocasiones_frecuentes", JSONB(astext_type=sa.Text()), server_default="[]", nullable=False),
        sa.Column("presupuesto_habitual", sa.Numeric(10, 2), nullable=True),
        sa.Column("silueta_preferida", sa.String(50), nullable=True),
        sa.Column("adn_estilo_ia", sa.Text(), nullable=True),
        sa.Column("primer_outfit_ia", JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("completado", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_perfiles_estilo_usuario_id", "perfiles_estilo_usuario", ["usuario_id"])

    # Trigger set_updated_at si la función existe
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_proc WHERE proname = 'set_updated_at') THEN
                CREATE TRIGGER trg_perfiles_estilo_usuario_updated_at
                BEFORE UPDATE ON perfiles_estilo_usuario
                FOR EACH ROW EXECUTE FUNCTION set_updated_at();
            END IF;
        END $$;
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_perfiles_estilo_usuario_updated_at ON perfiles_estilo_usuario;")
    op.drop_index("ix_perfiles_estilo_usuario_id", table_name="perfiles_estilo_usuario")
    op.drop_table("perfiles_estilo_usuario")
