# Backend funcional — Casos de uso CU-01 a CU-20

Este documento es la referencia del primer alcance de DrapeMind. La lógica de negocio vive en
FastAPI/PostgreSQL; Web y Móvil son consumidores. Base REST: `/api/v1`. Swagger: `/docs`.

## Cobertura

| CU | Capacidad | Canal consumidor | Endpoints principales | Estado backend |
|---|---|---|---|---|
| 01 | Registrar cliente | Móvil | `POST /auth/register` | Completo |
| 02 | Iniciar y mantener sesión | Web + Móvil | `POST /auth/login`, `POST /auth/token`, `GET /auth/me` | Completo |
| 03 | Perfil y direcciones | Web + Móvil | `PATCH /users/me`, CRUD `/users/me/addresses` | Completo |
| 04 | Consultar catálogo | Web + Móvil | `GET /catalog/products` | Completo |
| 05 | Buscar y filtrar | Web + Móvil | `GET /catalog/products?q=&categoria_id=&precio_min=&precio_max=&genero=&color=&talla=` | Completo |
| 06 | Detalle, talla, color y variante | Web + Móvil | `GET /catalog/products/{id}` | Completo |
| 07 | Disponibilidad por sucursal | Web + Móvil | `GET /branches`, `GET /branches/{id}/availability`, `GET /branches/products/{id}/availability` | Completo |
| 08 | Favoritos | Web + Móvil | `GET/POST/DELETE /catalog/favorites` | Completo |
| 09 | Carrito/perchero | Web + Móvil | CRUD `/cart` y `/cart/items` | Completo |
| 10 | Checkout, entrega o recojo | Web + Móvil | `POST /orders/checkout` | Completo |
| 11 | Pago electrónico | Web + Móvil + pasarela | `POST /payments`, consultas de pago, webhook HMAC | Completo |
| 12 | Pedidos e historial | Web + Móvil | `GET /orders`, `GET /orders/{id}` | Completo |
| 13 | Reserva multíprenda en sucursal | Web + Móvil | `POST /reservations` | Completo |
| 14 | Consultar, QR y cancelar reserva | Web + Móvil | `GET /reservations`, `GET /{id}/qr`, `POST /{id}/cancel` | Completo |
| 15 | Recibir y preparar reserva | Web operativo | `POST /reservations/{id}/prepare`, `POST /{id}/ready` | Completo |
| 16 | Atender llegada y convertir a venta | Web operativo | `POST /reservations/validate-qr`, `POST /{id}/convert-to-order` | Completo |
| 17 | Vestidor virtual AR | Móvil | `GET /ar/capabilities`, `GET /ar/products/{id}/try-on-config` | Backend completo |
| 18 | Asistente Altair | Web + Móvil | `POST /ai/chat`, `WS /ws/ai` | Completo |
| 19 | Búsqueda en lenguaje natural | Web + Móvil | `POST /ai/search`, tools de catálogo | Completo |
| 20 | Generar outfit | Web + Móvil | `POST /ai/outfits/generate`, tools de outfit | Completo |

En CU-17, FastAPI entrega assets, variantes, parámetros textiles y recomendación de talla. Cámara,
pose tracking y render 2D se ejecutan en Flutter; el backend no puede reemplazar esa responsabilidad.

## Roles y seguridad

- `CLIENTE`: cuenta pública, catálogo, favoritos, carrito, reservas, pedidos, pagos e IA.
- `ENCARGADO`: prepara y marca reservas listas en sus sucursales.
- `CAJERO`: valida llegada y convierte una reserva en venta en sus sucursales.
- `VENDEDOR`: rol heredado compatible con las tareas de encargado/cajero.
- `ADMIN`: configuración global y acceso a cualquier sucursal.

`POST /auth/register` nunca acepta un rol. El personal se crea internamente y se asigna con
`POST /branches/{branch_id}/staff`. Salvo ADMIN, una operación física exige una fila activa en
`personal_sucursal`.

## Sucursales y stock

El stock físico se guarda en `stock_sucursal` con `stock_total` y `stock_reservado`. Los campos
agregados de `variantes_producto` se sincronizan para conservar compatibilidad con catálogo,
carrito y herramientas de IA.

Rutas públicas:

- `GET /branches/cities`
- `GET /branches`
- `GET /branches/{branch_id}`
- `GET /branches/{branch_id}/availability`
- `GET /branches/products/{product_id}/availability`

Configuración ADMIN:

- `POST /branches/cities`
- `POST /branches`
- `PUT /branches/{branch_id}/stock`
- `POST /branches/{branch_id}/staff`

## Reserva multíprenda

Puede reservarse una lista explícita:

```json
{
  "sucursal_id": 1,
  "items": [
    {"variante_id": 12, "cantidad": 1},
    {"variante_id": 27, "cantidad": 2}
  ],
  "observacion": "Llegaré por la tarde"
}
```

Para compatibilidad, si `items` se omite se usa el carrito activo; si `sucursal_id` se omite se
selecciona la primera sucursal activa. En producción los clientes deben enviar la sede elegida.

La transacción bloquea con `SELECT ... FOR UPDATE` las filas de inventario de la sede. Si una sola
prenda no tiene stock, se revierte toda la reserva. La vigencia predeterminada es 2.880 minutos
(48 horas).

```text
PENDIENTE ──prepare──> EN_PREPARACION ──ready──> LISTA ──QR──> RETIRADA
    │                    │                         │                 │
    └────────────────────┴──────── cancel ─────────┘                 │
                                                                     │ convert-to-order
                                                                     v
                                                                 CONVERTIDA
```

Se conserva `CONFIRMADA` para compatibilidad con el check-in anticipado: si se valida el QR antes
de preparar, la reserva queda confirmada y luego puede pasar a `EN_PREPARACION`.

Cancelar o vencer libera `stock_reservado`; convertir descuenta total y reservado de la misma
sucursal y registra el movimiento de inventario. Cada cambio importante se publica por
`WS /api/v1/ws/events`.

## Pagos

`POST /payments` calcula el importe desde el pedido. Acepta `Idempotency-Key`: repetir la misma
solicitud devuelve el pago existente; reutilizar la clave con otro pedido o método produce 409.

- `GET /payments/{payment_id}`: estado puntual.
- `GET /payments/order/{order_id}`: intentos del pedido.
- `POST /payments/webhook`: valida `X-Webhook-Signature` (HMAC SHA-256) y confirma de forma idempotente.
- `POST /payments/{id}/mock-confirm`: sólo desarrollo con `PAYMENT_PROVIDER=mock`.

## AR

`GET /ar/capabilities` declara la separación backend/móvil. La configuración de producto devuelve:
asset, tallas y variantes con stock, tabla dimensional, elasticidad, tipo de ajuste, talla recomendada,
landmarks y limitaciones. Se corrigió la consulta de variantes para que no dependa de una relación ORM
inexistente.

## Instalación y actualización sin Docker

Base nueva:

```powershell
createdb -U postgres drapemind_db
psql -U postgres -d drapemind_db -f database/schema.sql
.\.venv\Scripts\python.exe scripts\seed_data.py
```

Base existente:

```powershell
.\.venv\Scripts\alembic.exe upgrade head
.\.venv\Scripts\python.exe scripts\seed_data.py
```

En Linux cambian únicamente las rutas del entorno virtual:

```bash
.venv/bin/alembic upgrade head
.venv/bin/python scripts/seed_data.py
```

Variables relevantes:

```dotenv
RESERVATION_TTL_MINUTES=2880
PAYMENT_PROVIDER=mock
PAYMENT_WEBHOOK_SECRET=un-secreto-largo
CORS_ORIGINS=["http://localhost:4200","https://tienda.midominio.com"]
```

## Verificación

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_contract.py tests\test_skills.py -q
.\.venv\Scripts\ruff.exe check app tests alembic\versions\20260827_01_cu01_20_branches.py
.\.venv\Scripts\python.exe -m scripts.check_cu01_20
```

La prueba de transacciones reales requiere PostgreSQL activo y `GET /health/ready` en estado 200.
