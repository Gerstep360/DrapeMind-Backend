-- ============================================================
-- TIENDA DE ROPA CON IA - PostgreSQL
-- Proyecto SI II
-- ============================================================

BEGIN;

CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS citext;

-- ---------- ENUMS ----------
CREATE TYPE rol_usuario AS ENUM ('CLIENTE', 'ADMIN', 'VENDEDOR', 'ENCARGADO', 'CAJERO');
CREATE TYPE estado_usuario AS ENUM ('ACTIVO', 'BLOQUEADO', 'INACTIVO');

CREATE TYPE genero_objetivo AS ENUM ('HOMBRE', 'MUJER', 'UNISEX', 'OTRO');

CREATE TYPE estado_carrito AS ENUM ('ACTIVO', 'CONVERTIDO', 'ABANDONADO');

CREATE TYPE tipo_movimiento_inventario AS ENUM (
    'ENTRADA',
    'VENTA',
    'RESERVA',
    'LIBERACION_RESERVA',
    'DEVOLUCION',
    'AJUSTE'
);

CREATE TYPE estado_reserva AS ENUM (
    'PENDIENTE',
    'CONFIRMADA',
    'EN_PREPARACION',
    'LISTA',
    'RETIRADA',
    'VENCIDA',
    'CANCELADA',
    'CONVERTIDA'
);

CREATE TYPE estado_pedido AS ENUM (
    'PENDIENTE_PAGO',
    'PAGADO',
    'PREPARANDO',
    'LISTO',
    'ENVIADO',
    'ENTREGADO',
    'CANCELADO'
);

CREATE TYPE canal_pedido AS ENUM ('MOBILE', 'WEB', 'TIENDA');
CREATE TYPE tipo_entrega AS ENUM ('DELIVERY', 'RECOJO', 'TIENDA');

CREATE TYPE metodo_pago AS ENUM ('QR', 'TARJETA', 'EFECTIVO', 'TRANSFERENCIA');
CREATE TYPE estado_pago AS ENUM ('PENDIENTE', 'PROCESANDO', 'APROBADO', 'RECHAZADO', 'REEMBOLSADO');

CREATE TYPE estado_ai_sesion AS ENUM ('ACTIVA', 'CERRADA', 'EXPIRADA');
CREATE TYPE tipo_ai_interaccion AS ENUM (
    'CHAT',
    'PRODUCT_SEARCH',
    'GENERATE_OUTFIT',
    'COMPLETE_OUTFIT',
    'STYLE_CHECK',
    'VALUE_CHECK'
);
CREATE TYPE estado_ai_interaccion AS ENUM ('OK', 'ERROR', 'CANCELADO');
CREATE TYPE tipo_ai_recomendacion AS ENUM (
    'OUTFIT',
    'REEMPLAZO_ESTILO',
    'REEMPLAZO_AHORRO',
    'REEMPLAZO_VALOR',
    'COMPLETAR_OUTFIT'
);
CREATE TYPE rol_prenda_outfit AS ENUM ('TOP', 'BOTTOM', 'SHOES', 'OUTERWEAR', 'ACCESSORY', 'OTHER');

-- ---------- FUNCIÓN updated_at ----------
CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- ============================================================
-- 1. USUARIOS
-- ============================================================
CREATE TABLE usuarios (
    id              BIGSERIAL PRIMARY KEY,
    nombre          VARCHAR(120) NOT NULL,
    email           CITEXT NOT NULL UNIQUE,
    password_hash   VARCHAR(255) NOT NULL,
    telefono        VARCHAR(30),
    rol             rol_usuario NOT NULL DEFAULT 'CLIENTE',
    estado          estado_usuario NOT NULL DEFAULT 'ACTIVO',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TRIGGER trg_usuarios_updated_at
BEFORE UPDATE ON usuarios
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ============================================================
-- 1B. CIUDADES, SUCURSALES Y PERSONAL
-- ============================================================
CREATE TABLE ciudades (
    id              BIGSERIAL PRIMARY KEY,
    nombre          VARCHAR(100) NOT NULL,
    departamento    VARCHAR(100) NOT NULL,
    activo          BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(nombre, departamento)
);

CREATE TABLE sucursales (
    id              BIGSERIAL PRIMARY KEY,
    ciudad_id       BIGINT NOT NULL REFERENCES ciudades(id) ON DELETE RESTRICT,
    codigo          VARCHAR(30) NOT NULL UNIQUE,
    nombre          VARCHAR(120) NOT NULL,
    direccion       VARCHAR(250) NOT NULL,
    telefono        VARCHAR(30),
    latitud         NUMERIC(9,6),
    longitud        NUMERIC(9,6),
    activo          BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (latitud IS NULL OR latitud BETWEEN -90 AND 90),
    CHECK (longitud IS NULL OR longitud BETWEEN -180 AND 180)
);

CREATE TABLE personal_sucursal (
    id              BIGSERIAL PRIMARY KEY,
    usuario_id      BIGINT NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
    sucursal_id     BIGINT NOT NULL REFERENCES sucursales(id) ON DELETE CASCADE,
    activo          BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(usuario_id, sucursal_id)
);

CREATE INDEX ix_personal_sucursal_usuario ON personal_sucursal(usuario_id, activo);
CREATE TRIGGER trg_ciudades_updated_at BEFORE UPDATE ON ciudades
FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_sucursales_updated_at BEFORE UPDATE ON sucursales
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ============================================================
-- 2. DIRECCIONES
-- ============================================================
CREATE TABLE direcciones (
    id                  BIGSERIAL PRIMARY KEY,
    usuario_id          BIGINT NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
    alias               VARCHAR(50) NOT NULL DEFAULT 'Casa',
    departamento        VARCHAR(80) NOT NULL,
    ciudad              VARCHAR(80) NOT NULL,
    zona                VARCHAR(100),
    direccion           VARCHAR(250) NOT NULL,
    referencia          VARCHAR(250),
    latitud             NUMERIC(9,6),
    longitud            NUMERIC(9,6),
    telefono_contacto   VARCHAR(30),
    es_principal        BOOLEAN NOT NULL DEFAULT FALSE,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (latitud IS NULL OR latitud BETWEEN -90 AND 90),
    CHECK (longitud IS NULL OR longitud BETWEEN -180 AND 180)
);

CREATE UNIQUE INDEX ux_direccion_principal_usuario
ON direcciones(usuario_id)
WHERE es_principal = TRUE;

CREATE TRIGGER trg_direcciones_updated_at
BEFORE UPDATE ON direcciones
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ============================================================
-- 3. CATEGORIAS
-- ============================================================
CREATE TABLE categorias (
    id              BIGSERIAL PRIMARY KEY,
    nombre          VARCHAR(80) NOT NULL,
    slug            VARCHAR(80) NOT NULL UNIQUE,
    descripcion     VARCHAR(250),
    parent_id       BIGINT REFERENCES categorias(id) ON DELETE SET NULL,
    activo          BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(parent_id, nombre)
);

CREATE TRIGGER trg_categorias_updated_at
BEFORE UPDATE ON categorias
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ============================================================
-- 4. PRODUCTOS
-- ============================================================
CREATE TABLE productos (
    id                  BIGSERIAL PRIMARY KEY,
    categoria_id        BIGINT NOT NULL REFERENCES categorias(id) ON DELETE RESTRICT,
    nombre              VARCHAR(150) NOT NULL,
    descripcion         TEXT,
    marca               VARCHAR(100),
    material            VARCHAR(150),
    precio              NUMERIC(10,2) NOT NULL,
    costo_referencia    NUMERIC(10,2),
    calidad_nivel       SMALLINT NOT NULL DEFAULT 3,
    genero_objetivo     genero_objetivo NOT NULL DEFAULT 'UNISEX',
    descripcion_ai      TEXT,
    tags_ai             TEXT[],
    imagenes            JSONB NOT NULL DEFAULT '[]'::jsonb,
    activo              BOOLEAN NOT NULL DEFAULT TRUE,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (precio >= 0),
    CHECK (costo_referencia IS NULL OR costo_referencia >= 0),
    CHECK (calidad_nivel BETWEEN 1 AND 5),
    CHECK (jsonb_typeof(imagenes) = 'array')
);

CREATE INDEX ix_productos_categoria_activo ON productos(categoria_id, activo);
CREATE INDEX ix_productos_precio ON productos(precio);
CREATE INDEX ix_productos_tags_ai ON productos USING GIN(tags_ai);

CREATE TRIGGER trg_productos_updated_at
BEFORE UPDATE ON productos
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ============================================================
-- 5. VARIANTES_PRODUCTO
-- ============================================================
CREATE TABLE variantes_producto (
    id                  BIGSERIAL PRIMARY KEY,
    producto_id         BIGINT NOT NULL REFERENCES productos(id) ON DELETE RESTRICT,
    sku                 VARCHAR(80) NOT NULL UNIQUE,
    color               VARCHAR(60) NOT NULL,
    codigo_color        VARCHAR(15),
    talla               VARCHAR(20) NOT NULL,
    stock_total         INTEGER NOT NULL DEFAULT 0,
    stock_reservado     INTEGER NOT NULL DEFAULT 0,
    codigo_barras       VARCHAR(100) UNIQUE,
    imagen              VARCHAR(500),
    activo              BOOLEAN NOT NULL DEFAULT TRUE,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (stock_total >= 0),
    CHECK (stock_reservado >= 0),
    CHECK (stock_reservado <= stock_total),
    UNIQUE(producto_id, color, talla)
);

CREATE INDEX ix_variantes_producto ON variantes_producto(producto_id, activo);
CREATE INDEX ix_variantes_stock ON variantes_producto(producto_id, stock_total, stock_reservado);

CREATE TRIGGER trg_variantes_updated_at
BEFORE UPDATE ON variantes_producto
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TABLE stock_sucursal (
    id                  BIGSERIAL PRIMARY KEY,
    sucursal_id         BIGINT NOT NULL REFERENCES sucursales(id) ON DELETE CASCADE,
    variante_id         BIGINT NOT NULL REFERENCES variantes_producto(id) ON DELETE RESTRICT,
    stock_total         INTEGER NOT NULL DEFAULT 0,
    stock_reservado     INTEGER NOT NULL DEFAULT 0,
    stock_minimo        INTEGER NOT NULL DEFAULT 0,
    activo              BOOLEAN NOT NULL DEFAULT TRUE,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (stock_total >= 0),
    CHECK (stock_reservado >= 0),
    CHECK (stock_minimo >= 0),
    CHECK (stock_reservado <= stock_total),
    UNIQUE(sucursal_id, variante_id)
);

CREATE INDEX ix_stock_sucursal_disponible
ON stock_sucursal(sucursal_id, activo, variante_id);
CREATE TRIGGER trg_stock_sucursal_updated_at BEFORE UPDATE ON stock_sucursal
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ============================================================
-- 6. MOVIMIENTOS_INVENTARIO
-- ============================================================
CREATE TABLE movimientos_inventario (
    id                          BIGSERIAL PRIMARY KEY,
    variante_id                 BIGINT NOT NULL REFERENCES variantes_producto(id) ON DELETE RESTRICT,
    sucursal_id                 BIGINT REFERENCES sucursales(id) ON DELETE SET NULL,
    tipo                        tipo_movimiento_inventario NOT NULL,
    cantidad                    INTEGER NOT NULL,
    stock_total_anterior        INTEGER NOT NULL,
    stock_total_nuevo           INTEGER NOT NULL,
    stock_reservado_anterior    INTEGER NOT NULL,
    stock_reservado_nuevo       INTEGER NOT NULL,
    referencia_tipo             VARCHAR(30),
    referencia_id               BIGINT,
    usuario_id                  BIGINT REFERENCES usuarios(id) ON DELETE SET NULL,
    observacion                 VARCHAR(300),
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (cantidad <> 0),
    CHECK (stock_total_anterior >= 0),
    CHECK (stock_total_nuevo >= 0),
    CHECK (stock_reservado_anterior >= 0),
    CHECK (stock_reservado_nuevo >= 0),
    CHECK (stock_reservado_anterior <= stock_total_anterior),
    CHECK (stock_reservado_nuevo <= stock_total_nuevo)
);

CREATE INDEX ix_movimientos_variante_fecha
ON movimientos_inventario(variante_id, created_at DESC);

CREATE INDEX ix_movimientos_referencia
ON movimientos_inventario(referencia_tipo, referencia_id);

-- ============================================================
-- 7. CARRITOS
-- ============================================================
CREATE TABLE carritos (
    id              BIGSERIAL PRIMARY KEY,
    usuario_id      BIGINT NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
    estado          estado_carrito NOT NULL DEFAULT 'ACTIVO',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX ux_carrito_activo_usuario
ON carritos(usuario_id)
WHERE estado = 'ACTIVO';

CREATE INDEX ix_carritos_usuario_estado ON carritos(usuario_id, estado);

CREATE TRIGGER trg_carritos_updated_at
BEFORE UPDATE ON carritos
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ============================================================
-- 8. ITEMS_CARRITO
-- ============================================================
CREATE TABLE items_carrito (
    id                  BIGSERIAL PRIMARY KEY,
    carrito_id          BIGINT NOT NULL REFERENCES carritos(id) ON DELETE CASCADE,
    variante_id         BIGINT NOT NULL REFERENCES variantes_producto(id) ON DELETE RESTRICT,
    cantidad            INTEGER NOT NULL DEFAULT 1,
    precio_referencia   NUMERIC(10,2) NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (cantidad > 0),
    CHECK (precio_referencia >= 0),
    UNIQUE(carrito_id, variante_id)
);

CREATE INDEX ix_items_carrito_carrito ON items_carrito(carrito_id);

CREATE TRIGGER trg_items_carrito_updated_at
BEFORE UPDATE ON items_carrito
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ============================================================
-- 9. RESERVAS
-- ============================================================
CREATE TABLE reservas (
    id              BIGSERIAL PRIMARY KEY,
    codigo_publico  UUID NOT NULL UNIQUE DEFAULT gen_random_uuid(),
    usuario_id      BIGINT NOT NULL REFERENCES usuarios(id) ON DELETE RESTRICT,
    sucursal_id     BIGINT REFERENCES sucursales(id) ON DELETE RESTRICT,
    estado          estado_reserva NOT NULL DEFAULT 'PENDIENTE',
    fecha_reserva   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    vence_at        TIMESTAMPTZ NOT NULL,
    qr_token        UUID NOT NULL UNIQUE DEFAULT gen_random_uuid(),
    observacion     VARCHAR(300),
    preparado_por_id BIGINT REFERENCES usuarios(id) ON DELETE SET NULL,
    preparado_at     TIMESTAMPTZ,
    atendido_por_id  BIGINT REFERENCES usuarios(id) ON DELETE SET NULL,
    atendido_at      TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (vence_at > fecha_reserva)
);

CREATE INDEX ix_reservas_usuario_estado ON reservas(usuario_id, estado);
CREATE INDEX ix_reservas_vence_at ON reservas(vence_at);
CREATE INDEX ix_reservas_sucursal_estado ON reservas(sucursal_id, estado, vence_at);

CREATE TRIGGER trg_reservas_updated_at
BEFORE UPDATE ON reservas
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ============================================================
-- 10. ITEMS_RESERVA
-- ============================================================
CREATE TABLE items_reserva (
    id                  BIGSERIAL PRIMARY KEY,
    reserva_id          BIGINT NOT NULL REFERENCES reservas(id) ON DELETE CASCADE,
    variante_id         BIGINT NOT NULL REFERENCES variantes_producto(id) ON DELETE RESTRICT,
    cantidad            INTEGER NOT NULL DEFAULT 1,
    precio_referencia   NUMERIC(10,2) NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (cantidad > 0),
    CHECK (precio_referencia >= 0),
    UNIQUE(reserva_id, variante_id)
);

CREATE INDEX ix_items_reserva_reserva ON items_reserva(reserva_id);

-- ============================================================
-- 11. PEDIDOS
-- ============================================================
CREATE TABLE pedidos (
    id                          BIGSERIAL PRIMARY KEY,
    codigo_publico              UUID NOT NULL UNIQUE DEFAULT gen_random_uuid(),
    usuario_id                  BIGINT NOT NULL REFERENCES usuarios(id) ON DELETE RESTRICT,
    reserva_id                  BIGINT UNIQUE REFERENCES reservas(id) ON DELETE SET NULL,
    sucursal_id                 BIGINT REFERENCES sucursales(id) ON DELETE SET NULL,
    estado                      estado_pedido NOT NULL DEFAULT 'PENDIENTE_PAGO',
    canal                       canal_pedido NOT NULL,
    tipo_entrega                tipo_entrega NOT NULL,
    subtotal                    NUMERIC(10,2) NOT NULL DEFAULT 0,
    descuento                   NUMERIC(10,2) NOT NULL DEFAULT 0,
    costo_envio                 NUMERIC(10,2) NOT NULL DEFAULT 0,
    total                       NUMERIC(10,2) NOT NULL DEFAULT 0,
    direccion_entrega_snapshot  JSONB,
    observacion                 VARCHAR(300),
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    paid_at                     TIMESTAMPTZ,
    completed_at                TIMESTAMPTZ,
    cancelled_at                TIMESTAMPTZ,
    CHECK (subtotal >= 0),
    CHECK (descuento >= 0),
    CHECK (costo_envio >= 0),
    CHECK (total >= 0),
    CHECK (descuento <= subtotal),
    CHECK (total = subtotal - descuento + costo_envio),
    CHECK (
        direccion_entrega_snapshot IS NULL
        OR jsonb_typeof(direccion_entrega_snapshot) IN ('object', 'null')
    )
);

CREATE INDEX ix_pedidos_usuario_estado ON pedidos(usuario_id, estado);
CREATE INDEX ix_pedidos_fecha ON pedidos(created_at DESC);
CREATE INDEX ix_pedidos_estado_fecha ON pedidos(estado, created_at DESC);
CREATE INDEX ix_pedidos_sucursal_estado ON pedidos(sucursal_id, estado);

CREATE TRIGGER trg_pedidos_updated_at
BEFORE UPDATE ON pedidos
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ============================================================
-- 12. ITEMS_PEDIDO
-- ============================================================
CREATE TABLE items_pedido (
    id                  BIGSERIAL PRIMARY KEY,
    pedido_id           BIGINT NOT NULL REFERENCES pedidos(id) ON DELETE RESTRICT,
    producto_id         BIGINT REFERENCES productos(id) ON DELETE SET NULL,
    variante_id         BIGINT REFERENCES variantes_producto(id) ON DELETE SET NULL,
    nombre_snapshot     VARCHAR(150) NOT NULL,
    sku_snapshot        VARCHAR(80) NOT NULL,
    color_snapshot      VARCHAR(60) NOT NULL,
    talla_snapshot      VARCHAR(20) NOT NULL,
    cantidad            INTEGER NOT NULL,
    precio_unitario     NUMERIC(10,2) NOT NULL,
    descuento           NUMERIC(10,2) NOT NULL DEFAULT 0,
    subtotal            NUMERIC(10,2) NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (cantidad > 0),
    CHECK (precio_unitario >= 0),
    CHECK (descuento >= 0),
    CHECK (subtotal >= 0),
    CHECK (descuento <= precio_unitario * cantidad),
    CHECK (subtotal = (precio_unitario * cantidad) - descuento)
);

CREATE INDEX ix_items_pedido_pedido ON items_pedido(pedido_id);
CREATE INDEX ix_items_pedido_producto ON items_pedido(producto_id);

-- ============================================================
-- 13. PAGOS
-- ============================================================
CREATE TABLE pagos (
    id                  BIGSERIAL PRIMARY KEY,
    pedido_id           BIGINT NOT NULL REFERENCES pedidos(id) ON DELETE RESTRICT,
    metodo              metodo_pago NOT NULL,
    proveedor           VARCHAR(80),
    monto               NUMERIC(10,2) NOT NULL,
    moneda              CHAR(3) NOT NULL DEFAULT 'BOB',
    estado              estado_pago NOT NULL DEFAULT 'PENDIENTE',
    referencia_externa  VARCHAR(200),
    idempotency_key     VARCHAR(100),
    qr_payload           TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    paid_at             TIMESTAMPTZ,
    CHECK (monto > 0)
);

CREATE INDEX ix_pagos_pedido_estado ON pagos(pedido_id, estado);
CREATE UNIQUE INDEX ux_pago_referencia_externa
ON pagos(referencia_externa)
WHERE referencia_externa IS NOT NULL;
CREATE UNIQUE INDEX ux_pagos_idempotency_key
ON pagos(idempotency_key)
WHERE idempotency_key IS NOT NULL;

-- ============================================================
-- 14. FAVORITOS
-- ============================================================
CREATE TABLE favoritos (
    id              BIGSERIAL PRIMARY KEY,
    usuario_id      BIGINT NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
    producto_id     BIGINT NOT NULL REFERENCES productos(id) ON DELETE CASCADE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(usuario_id, producto_id)
);

CREATE INDEX ix_favoritos_usuario ON favoritos(usuario_id);

-- ============================================================
-- 15. AI_SESIONES
-- ============================================================
CREATE TABLE ai_sesiones (
    id                  BIGSERIAL PRIMARY KEY,
    usuario_id          BIGINT NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
    estado              estado_ai_sesion NOT NULL DEFAULT 'ACTIVA',
    resumen_contexto    TEXT,
    started_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_activity_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    closed_at           TIMESTAMPTZ
);

CREATE INDEX ix_ai_sesiones_usuario_estado
ON ai_sesiones(usuario_id, estado);

-- ============================================================
-- 16. AI_INTERACCIONES
-- ============================================================
CREATE TABLE ai_interacciones (
    id                  BIGSERIAL PRIMARY KEY,
    sesion_id           BIGINT NOT NULL REFERENCES ai_sesiones(id) ON DELETE CASCADE,
    tipo                tipo_ai_interaccion NOT NULL,
    intent              VARCHAR(40),
    mensaje_usuario     TEXT,
    respuesta           TEXT,
    tool_principal      VARCHAR(60),
    duracion_ms         INTEGER,
    tokens_entrada      INTEGER,
    tokens_salida       INTEGER,
    modelo              VARCHAR(80) NOT NULL DEFAULT 'gemma-4-e2b-it',
    estado              estado_ai_interaccion NOT NULL DEFAULT 'OK',
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (duracion_ms IS NULL OR duracion_ms >= 0),
    CHECK (tokens_entrada IS NULL OR tokens_entrada >= 0),
    CHECK (tokens_salida IS NULL OR tokens_salida >= 0)
);

CREATE INDEX ix_ai_interacciones_sesion_fecha
ON ai_interacciones(sesion_id, created_at DESC);

CREATE INDEX ix_ai_interacciones_tipo_fecha
ON ai_interacciones(tipo, created_at DESC);

-- ============================================================
-- 17. AI_RECOMENDACIONES
-- ============================================================
CREATE TABLE ai_recomendaciones (
    id                          BIGSERIAL PRIMARY KEY,
    interaccion_id              BIGINT NOT NULL REFERENCES ai_interacciones(id) ON DELETE CASCADE,
    grupo_uuid                  UUID NOT NULL DEFAULT gen_random_uuid(),
    tipo                        tipo_ai_recomendacion NOT NULL,
    rol                         rol_prenda_outfit,
    producto_origen_id          BIGINT REFERENCES productos(id) ON DELETE SET NULL,
    variante_origen_id          BIGINT REFERENCES variantes_producto(id) ON DELETE SET NULL,
    producto_recomendado_id     BIGINT NOT NULL REFERENCES productos(id) ON DELETE RESTRICT,
    variante_recomendada_id     BIGINT REFERENCES variantes_producto(id) ON DELETE SET NULL,
    score                       NUMERIC(5,4),
    ahorro                      NUMERIC(10,2),
    motivo_corto                VARCHAR(300),
    aceptada                    BOOLEAN,
    aplicada                    BOOLEAN NOT NULL DEFAULT FALSE,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    applied_at                  TIMESTAMPTZ,
    CHECK (score IS NULL OR score BETWEEN 0 AND 1),
    CHECK (ahorro IS NULL OR ahorro >= 0),
    CHECK (aplicada = FALSE OR aceptada = TRUE)
);

CREATE INDEX ix_ai_recomendaciones_interaccion
ON ai_recomendaciones(interaccion_id);

CREATE INDEX ix_ai_recomendaciones_grupo
ON ai_recomendaciones(grupo_uuid);

CREATE INDEX ix_ai_recomendaciones_producto
ON ai_recomendaciones(producto_recomendado_id);

-- ============================================================
-- VISTAS ÚTILES
-- ============================================================

CREATE VIEW vw_stock_disponible AS
SELECT
    vp.id AS variante_id,
    vp.producto_id,
    vp.sku,
    vp.color,
    vp.talla,
    vp.stock_total,
    vp.stock_reservado,
    (vp.stock_total - vp.stock_reservado) AS stock_disponible,
    vp.activo
FROM variantes_producto vp;

CREATE VIEW vw_historial_ventas AS
SELECT
    p.id AS pedido_id,
    p.codigo_publico,
    p.usuario_id,
    u.nombre AS cliente,
    p.canal,
    p.tipo_entrega,
    p.subtotal,
    p.descuento,
    p.costo_envio,
    p.total,
    p.created_at,
    p.completed_at
FROM pedidos p
JOIN usuarios u ON u.id = p.usuario_id
WHERE p.estado = 'ENTREGADO';

CREATE VIEW vw_resumen_ai AS
SELECT
    ai.tipo,
    COUNT(*) AS total_interacciones,
    AVG(ai.duracion_ms)::NUMERIC(12,2) AS duracion_promedio_ms,
    SUM(CASE WHEN ai.estado = 'OK' THEN 1 ELSE 0 END) AS exitosas,
    SUM(CASE WHEN ai.estado = 'ERROR' THEN 1 ELSE 0 END) AS errores
FROM ai_interacciones ai
GROUP BY ai.tipo;

COMMIT;

-- ============================================================
-- NOTA DE IMPLEMENTACIÓN
-- Para reservar/comprar stock, FastAPI debe usar transacciones y
-- SELECT ... FOR UPDATE sobre variantes_producto para evitar
-- sobreventa cuando dos usuarios actúan al mismo tiempo.
-- ============================================================
