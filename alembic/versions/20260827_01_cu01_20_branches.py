"""CU-01..CU-20: sucursales, inventario por sede y reservas operativas."""

from alembic import op

revision = "20260827_01"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE rol_usuario ADD VALUE IF NOT EXISTS 'ENCARGADO'")
    op.execute("ALTER TYPE rol_usuario ADD VALUE IF NOT EXISTS 'CAJERO'")
    op.execute("ALTER TYPE estado_reserva ADD VALUE IF NOT EXISTS 'EN_PREPARACION'")
    op.execute("ALTER TYPE estado_reserva ADD VALUE IF NOT EXISTS 'LISTA'")
    op.execute("""
        CREATE TABLE IF NOT EXISTS ciudades (
            id BIGSERIAL PRIMARY KEY, nombre VARCHAR(100) NOT NULL,
            departamento VARCHAR(100) NOT NULL, activo BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_ciudad_nombre_departamento UNIQUE(nombre, departamento)
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS sucursales (
            id BIGSERIAL PRIMARY KEY, ciudad_id BIGINT NOT NULL REFERENCES ciudades(id) ON DELETE RESTRICT,
            codigo VARCHAR(30) NOT NULL UNIQUE, nombre VARCHAR(120) NOT NULL,
            direccion VARCHAR(250) NOT NULL, telefono VARCHAR(30),
            latitud NUMERIC(9,6), longitud NUMERIC(9,6), activo BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CHECK (latitud IS NULL OR latitud BETWEEN -90 AND 90),
            CHECK (longitud IS NULL OR longitud BETWEEN -180 AND 180)
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS personal_sucursal (
            id BIGSERIAL PRIMARY KEY, usuario_id BIGINT NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
            sucursal_id BIGINT NOT NULL REFERENCES sucursales(id) ON DELETE CASCADE,
            activo BOOLEAN NOT NULL DEFAULT TRUE, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_personal_usuario_sucursal UNIQUE(usuario_id, sucursal_id)
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS stock_sucursal (
            id BIGSERIAL PRIMARY KEY, sucursal_id BIGINT NOT NULL REFERENCES sucursales(id) ON DELETE CASCADE,
            variante_id BIGINT NOT NULL REFERENCES variantes_producto(id) ON DELETE RESTRICT,
            stock_total INTEGER NOT NULL DEFAULT 0, stock_reservado INTEGER NOT NULL DEFAULT 0,
            stock_minimo INTEGER NOT NULL DEFAULT 0, activo BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_stock_sucursal_variante UNIQUE(sucursal_id, variante_id),
            CHECK (stock_total >= 0), CHECK (stock_reservado >= 0),
            CHECK (stock_minimo >= 0), CHECK (stock_reservado <= stock_total)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_stock_sucursal_disponible ON stock_sucursal(sucursal_id, activo, variante_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_personal_sucursal_usuario ON personal_sucursal(usuario_id, activo)")
    op.execute("ALTER TABLE reservas ADD COLUMN IF NOT EXISTS sucursal_id BIGINT REFERENCES sucursales(id) ON DELETE RESTRICT")
    op.execute("ALTER TABLE reservas ADD COLUMN IF NOT EXISTS preparado_por_id BIGINT REFERENCES usuarios(id) ON DELETE SET NULL")
    op.execute("ALTER TABLE reservas ADD COLUMN IF NOT EXISTS preparado_at TIMESTAMPTZ")
    op.execute("ALTER TABLE reservas ADD COLUMN IF NOT EXISTS atendido_por_id BIGINT REFERENCES usuarios(id) ON DELETE SET NULL")
    op.execute("ALTER TABLE reservas ADD COLUMN IF NOT EXISTS atendido_at TIMESTAMPTZ")
    op.execute("CREATE INDEX IF NOT EXISTS ix_reservas_sucursal_estado ON reservas(sucursal_id, estado, vence_at)")
    op.execute("ALTER TABLE pedidos ADD COLUMN IF NOT EXISTS sucursal_id BIGINT REFERENCES sucursales(id) ON DELETE SET NULL")
    op.execute("CREATE INDEX IF NOT EXISTS ix_pedidos_sucursal_estado ON pedidos(sucursal_id, estado)")
    op.execute("ALTER TABLE pagos ADD COLUMN IF NOT EXISTS idempotency_key VARCHAR(100)")
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_pagos_idempotency_key ON pagos(idempotency_key) WHERE idempotency_key IS NOT NULL")
    op.execute("ALTER TABLE movimientos_inventario ADD COLUMN IF NOT EXISTS sucursal_id BIGINT REFERENCES sucursales(id) ON DELETE SET NULL")
    op.execute("""
        INSERT INTO ciudades(nombre, departamento) VALUES ('Santa Cruz de la Sierra', 'Santa Cruz')
        ON CONFLICT (nombre, departamento) DO NOTHING
    """)
    op.execute("""
        INSERT INTO sucursales(ciudad_id, codigo, nombre, direccion, telefono)
        SELECT id, 'SCZ-CENTRAL', 'DrapeMind Central', 'Av. San Martín, Equipetrol', '70000000'
        FROM ciudades WHERE nombre='Santa Cruz de la Sierra' AND departamento='Santa Cruz'
        ON CONFLICT (codigo) DO NOTHING
    """)
    op.execute("""
        INSERT INTO stock_sucursal(sucursal_id, variante_id, stock_total, stock_reservado)
        SELECT s.id, v.id, v.stock_total, v.stock_reservado
        FROM sucursales s CROSS JOIN variantes_producto v WHERE s.codigo='SCZ-CENTRAL'
        ON CONFLICT (sucursal_id, variante_id) DO NOTHING
    """)
    op.execute("""
        UPDATE reservas SET sucursal_id=(SELECT id FROM sucursales WHERE codigo='SCZ-CENTRAL')
        WHERE sucursal_id IS NULL
    """)
    op.execute("""
        INSERT INTO personal_sucursal(usuario_id, sucursal_id)
        SELECT u.id, s.id FROM usuarios u CROSS JOIN sucursales s
        WHERE u.rol='VENDEDOR' AND s.codigo='SCZ-CENTRAL'
        ON CONFLICT (usuario_id, sucursal_id) DO NOTHING
    """)
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname='trg_ciudades_updated_at') THEN
                CREATE TRIGGER trg_ciudades_updated_at BEFORE UPDATE ON ciudades
                FOR EACH ROW EXECUTE FUNCTION set_updated_at();
            END IF;
            IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname='trg_sucursales_updated_at') THEN
                CREATE TRIGGER trg_sucursales_updated_at BEFORE UPDATE ON sucursales
                FOR EACH ROW EXECUTE FUNCTION set_updated_at();
            END IF;
            IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname='trg_stock_sucursal_updated_at') THEN
                CREATE TRIGGER trg_stock_sucursal_updated_at BEFORE UPDATE ON stock_sucursal
                FOR EACH ROW EXECUTE FUNCTION set_updated_at();
            END IF;
        END $$;
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE movimientos_inventario DROP COLUMN IF EXISTS sucursal_id")
    op.execute("DROP INDEX IF EXISTS ux_pagos_idempotency_key")
    op.execute("ALTER TABLE pagos DROP COLUMN IF EXISTS idempotency_key")
    op.execute("ALTER TABLE pedidos DROP COLUMN IF EXISTS sucursal_id")
    op.execute("ALTER TABLE reservas DROP COLUMN IF EXISTS atendido_at")
    op.execute("ALTER TABLE reservas DROP COLUMN IF EXISTS atendido_por_id")
    op.execute("ALTER TABLE reservas DROP COLUMN IF EXISTS preparado_at")
    op.execute("ALTER TABLE reservas DROP COLUMN IF EXISTS preparado_por_id")
    op.execute("ALTER TABLE reservas DROP COLUMN IF EXISTS sucursal_id")
    op.execute("DROP TABLE IF EXISTS stock_sucursal")
    op.execute("DROP TABLE IF EXISTS personal_sucursal")
    op.execute("DROP TABLE IF EXISTS sucursales")
    op.execute("DROP TABLE IF EXISTS ciudades")
