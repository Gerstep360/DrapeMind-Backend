"""Create notification and device tables used by login and the notification API."""
from alembic import op

revision = '20261015_02'
down_revision = '20261015_01'
branch_labels = None
depends_on = None

def upgrade():
    op.execute('''CREATE TABLE IF NOT EXISTS dispositivos_usuario (
        id BIGSERIAL PRIMARY KEY,
        usuario_id BIGINT NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
        token VARCHAR(500) NOT NULL,
        dispositivo_id VARCHAR(120),
        plataforma VARCHAR(30) NOT NULL DEFAULT 'android',
        modelo VARCHAR(100),
        activo BOOLEAN NOT NULL DEFAULT true,
        ultimo_uso TIMESTAMPTZ NOT NULL DEFAULT now(),
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        CONSTRAINT uq_dispositivo_usuario_token UNIQUE (usuario_id, token)
    )''')
    op.execute('CREATE UNIQUE INDEX IF NOT EXISTS ix_dispositivos_usuario_token ON dispositivos_usuario(token)')
    op.execute('CREATE INDEX IF NOT EXISTS ix_dispositivos_usuario_usuario_id ON dispositivos_usuario(usuario_id)')
    op.execute('''CREATE TABLE IF NOT EXISTS notificaciones (
        id BIGSERIAL PRIMARY KEY,
        usuario_id BIGINT REFERENCES usuarios(id) ON DELETE CASCADE,
        titulo VARCHAR(150) NOT NULL,
        mensaje TEXT NOT NULL,
        tipo VARCHAR(50) NOT NULL DEFAULT 'GENERAL',
        data_payload JSONB,
        leido BOOLEAN NOT NULL DEFAULT false,
        leido_en TIMESTAMPTZ,
        dispositivo_origen_id VARCHAR(120),
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )''')
    op.execute('CREATE INDEX IF NOT EXISTS ix_notificaciones_usuario_id ON notificaciones(usuario_id)')

def downgrade():
    op.drop_table('notificaciones')
    op.drop_table('dispositivos_usuario')
