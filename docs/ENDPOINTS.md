# Endpoints DrapeMind API v1

Base URL: `/api/v1`. Las rutas marcadas como autenticadas usan
`Authorization: Bearer <JWT>`. Swagger mantiene los schemas request/response y ejemplos de error.

## Autenticacion y cliente

| Metodo | Ruta | Acceso | Caso | Funcion |
|---|---|---|---|---|
| POST | `/auth/register` | Publico | CU-01 | Registra exclusivamente un CLIENTE |
| POST | `/auth/login` | Publico | CU-02 | Login JSON para Angular/Flutter |
| POST | `/auth/token` | Publico | CU-02 | Login OAuth2 para Swagger |
| GET | `/auth/me` | Autenticado | CU-02 | Datos derivados del JWT |
| PATCH | `/users/me` | Autenticado | CU-03 | Actualiza perfil |
| GET/POST | `/users/me/addresses` | CLIENTE | CU-03 | Lista/crea direcciones |
| PUT/DELETE | `/users/me/addresses/{id}` | Propietario | CU-03 | Edita/elimina direccion |

## Catalogo, favoritos y carrito

| Metodo | Ruta | Acceso | Caso | Funcion |
|---|---|---|---|---|
| GET | `/catalog/categories` | Publico | CU-04 | Categorias activas |
| GET | `/catalog/products` | Publico | CU-04/05 | Busca y filtra por categoria, precio, genero, color, talla y stock |
| GET | `/catalog/products/{id}` | Publico | CU-06 | Detalle, variantes y stock disponible |
| GET/POST/DELETE | `/catalog/favorites[/{product_id}]` | CLIENTE | CU-07 | Gestiona favoritos |
| GET | `/cart` | CLIENTE | CU-16/17 | Carrito activo |
| POST | `/cart/items` | CLIENTE | CU-16 | Agrega variante con validacion de stock |
| PATCH/DELETE | `/cart/items/{id}` | Propietario | CU-17 | Cambia cantidad/elimina |
| POST | `/cart/replace` | Propietario | CU-14 | Reemplazo seguro usado por IA |

## IA y AR

| Metodo | Ruta | Caso | Tool/capacidad controlada |
|---|---|---|---|
| POST | `/ai/chat` | CU-08 | `get_my_cart + search_products` |
| POST | `/ai/search` | CU-09 | extraccion Gemma + `search_products` parametrizado |
| POST | `/ai/outfits/generate` | CU-10 | catalogo + stock |
| POST | `/ai/outfits/complete` | CU-11 | producto base + alternativas |
| POST | `/ai/cart/style-check` | CU-12 | carrito real + catalogo |
| POST | `/ai/cart/value-check` | CU-13 | comparacion determinista calidad/precio |
| POST | `/ai/recommendations/apply` | CU-14 | propiedad + `replace_cart_item` + revalidacion |
| GET | `/ar/products/{id}/try-on-config` | CU-15 | asset AR autorizado; camara/render en Flutter |

Todas las interacciones guardan sesion, tipo, modelo, duracion y tokens cuando el servidor los reporta.
Las recomendaciones guardan aceptacion/aplicacion para auditoria.

### WebSockets autenticados

| Canal | Primer frame | Eventos de salida |
|---|---|---|
| `/ws/ai` | `{"type":"auth","token":"JWT"}` | `connected`, `model_status`, `tool_start`, `tool_result`, `token`, `done`, `error` |
| `/ws/events` | `{"type":"auth","token":"JWT"}` | cambios de reserva, pedido, pago e inventario |

Tras autenticar `/ws/ai`, la consulta usa
`{"type":"chat","message":"...","session_id":"opcional"}`. El runtime se carga bajo
demanda y se libera despues de `AI_IDLE_TIMEOUT_SECONDS` sin actividad.

## Reservas, pedidos y pagos

| Metodo | Ruta | Acceso | Caso | Funcion |
|---|---|---|---|---|
| POST | `/reservations` | CLIENTE | CU-18 | Convierte carrito en reserva y bloquea stock |
| GET | `/reservations[/{id}]` | Propietario | CU-18/20 | Lista/consulta |
| GET | `/reservations/{id}/qr` | Propietario | CU-19 | PNG con token aleatorio |
| POST | `/reservations/{id}/cancel` | Propietario | CU-20 | Libera stock reservado |
| POST | `/reservations/validate-qr` | ADMIN/VENDEDOR | CU-21 | Valida token, estado y vencimiento |
| POST | `/reservations/{id}/convert-to-order` | ADMIN/VENDEDOR | CU-22 | Consume reserva y crea pedido de tienda |
| POST | `/orders/checkout` | CLIENTE | CU-23/24 | Carrito a pedido, snapshot de direccion y stock |
| GET | `/orders[/{id}]` | Propietario | CU-27 | Historial/estado |
| PATCH | `/orders/{id}/status` | ADMIN/VENDEDOR | CU-33 | Maquina de estados |
| POST | `/payments` | Propietario | CU-25 | Inicia pago con monto del servidor |
| POST | `/payments/webhook` | Pasarela HMAC | CU-26 | Confirma resultado idempotente |
| POST | `/payments/{id}/mock-confirm` | Propietario/dev | CU-25/26 | Demo local, nunca produccion |

Las reservas, checkout, conversion y ajustes usan `SELECT ... FOR UPDATE` y
`movimientos_inventario` para evitar sobreventa y dejar auditoria.

## Administracion

Prefijo `/admin`.

| Metodo | Ruta | Rol | Caso |
|---|---|---|---|
| POST/PUT | `/categories[/{id}]` | ADMIN | CU-28 |
| POST/PUT | `/products[/{id}]` | ADMIN | CU-28 |
| POST | `/products/{id}/variants` | ADMIN | CU-29 |
| PUT | `/variants/{id}` | ADMIN | CU-29 |
| POST | `/inventory/adjustments` | ADMIN | CU-30 |
| POST | `/products/ai-draft` | ADMIN | CU-31; solo borrador, exige validacion humana |
| GET | `/reservations` | ADMIN/VENDEDOR | CU-32 |
| POST | `/reservations/expire-due` | ADMIN | CU-20/32; libera stock vencido con SKIP LOCKED |
| GET | `/orders` | ADMIN/VENDEDOR | CU-33 |
| GET | `/sales/history` | ADMIN | CU-34; vista `vw_historial_ventas` |
| GET | `/metrics/sales-inventory` | ADMIN | CU-35 |
| GET | `/metrics/ai` | ADMIN | CU-36; vista `vw_resumen_ai` |
| GET | `/ai/runtime` | ADMIN | Estado, plataforma, modelo y tiempo inactivo |
| POST | `/ai/runtime/start` | ADMIN | Inicia llama-server bajo demanda |
| POST | `/ai/runtime/stop` | ADMIN | Libera manualmente el modelo |

## Codigos de error

- `400/422`: request invalido.
- `401`: JWT/webhook invalido.
- `403`: cuenta o rol sin permiso.
- `404`: recurso inexistente o ajeno (evita enumeracion).
- `409`: conflicto de estado, duplicado o stock insuficiente.
- `410`: reserva vencida.
- `503`: PostgreSQL/Gemma no disponible, segun endpoint.
