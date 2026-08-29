# Endpoints DrapeMind API v1

> La trazabilidad vigente y compactada de **CU-01 a CU-20** está en
> [CU01_20_BACKEND.md](CU01_20_BACKEND.md). Las numeraciones históricas de este inventario extendido
> se conservan sólo como referencia del alcance futuro.

Base URL: `/api/v1`. Las rutas marcadas como autenticadas usan
`Authorization: Bearer <JWT>`. Swagger mantiene los schemas request/response y ejemplos de error.

## 1. Autenticación y Cuentas de Usuario

| Método | Ruta | Acceso | Caso | Descripción |
|---|---|---|---|---|
| POST | `/auth/register` | Público | CU-01 | Registra exclusivamente un nuevo usuario con rol `CLIENTE`. |
| POST | `/auth/login` | Público | CU-02 | Inicio de sesión JSON (email y contraseña); devuelve JWT Bearer. |
| POST | `/auth/token` | Público | CU-02 | Variante OAuth2 Password Flow para Swagger UI. |
| GET | `/auth/me` | Autenticado | CU-03 | Consulta de datos y rol del usuario autenticado actual. |
| PATCH | `/users/me` | Autenticado | CU-04 | Actualización de nombre y teléfono del perfil del cliente. |
| GET | `/users/me/addresses` | CLIENTE | CU-05 | Lista las direcciones de envío registradas por el cliente. |
| POST | `/users/me/addresses` | CLIENTE | CU-05 | Crea una nueva dirección; si es principal, desmarca la anterior. |
| PUT | `/users/me/addresses/{id}` | Propietario | CU-05 | Actualiza datos y coordenadas de una dirección existente. |
| DELETE | `/users/me/addresses/{id}` | Propietario | CU-05 | Elimina una dirección de la libreta del cliente. |

## 2. Catálogo Comercial y Preferencias

| Método | Ruta | Acceso | Caso | Descripción |
|---|---|---|---|---|
| GET | `/catalog/categories` | Público | CU-06 | Listado de categorías comerciales activas. |
| GET | `/catalog/products` | Público | CU-07 | Búsqueda y filtrado multicriterio (texto, categoría, precio, género, color, talla, stock). |
| GET | `/catalog/products/{id}` | Público | CU-08 | Detalle completo de prenda, materiales, fotos y variantes con stock real. |
| GET | `/catalog/favorites` | CLIENTE | CU-09 | Lista los productos marcados como favoritos por el cliente. |
| POST | `/catalog/favorites/{product_id}` | CLIENTE | CU-09 | Agrega un producto a la lista de deseos/favoritos. |
| DELETE | `/catalog/favorites/{product_id}` | CLIENTE | CU-09 | Remueve un producto de la lista de favoritos. |

## 3. Carrito de Compras Transaccional (Perchero)

| Método | Ruta | Acceso | Caso | Descripción |
|---|---|---|---|---|
| GET | `/cart` | CLIENTE | CU-10 | Consulta de prendas en el carrito con recálculo de subtotales en backend. |
| POST | `/cart/items` | CLIENTE | CU-11 | Agrega una prenda individual con validación de stock disponible. |
| POST | `/cart/items/batch` | CLIENTE | CU-12 | Agrega un outfit completo atómicamente; si una prenda falla, revierte todo. |
| PUT | `/cart/items/batch` | CLIENTE | CU-13 | Reemplaza el carrito entero por una selección de IA de forma transaccional. |
| PATCH | `/cart/items/{id}` | Propietario | CU-14 | Modifica la cantidad de una prenda en el carrito. |
| DELETE | `/cart/items/{id}` | Propietario | CU-15 | Elimina una prenda del carrito de compras. |
| POST | `/cart/replace` | Propietario | CU-16 | Sustitución segura de una prenda por una alternativa sugerida por IA. |

## 4. Reservas Presenciales y Showroom (48 Horas)

| Método | Ruta | Acceso | Caso | Descripción |
|---|---|---|---|---|
| POST | `/reservations` | CLIENTE | CU-17 | Convierte el carrito en reserva de 48h y bloquea unidades en `stock_reservado`. |
| GET | `/reservations` | CLIENTE | CU-18 | Listado de reservas activas e históricas del cliente. |
| GET | `/reservations/{id}` | Propietario | CU-18 | Consulta del estado y detalle de una reserva específica. |
| GET | `/reservations/{id}/qr` | Propietario | CU-19 | Genera imagen PNG del código QR criptoseguro (token UUID). |
| POST | `/reservations/{id}/cancel` | Propietario | CU-20 | Cancela la reserva y libera de inmediato el `stock_reservado`. |
| POST | `/reservations/validate-qr` | ADMIN/VENDEDOR | CU-21 | Escaneo y validación de QR en tienda física para check-in de cliente. |
| POST | `/reservations/{id}/convert-to-order` | ADMIN/VENDEDOR | CU-22 | Convierte la reserva en venta presencial consumiendo el stock reservado. |

## 5. Pedidos, Logística y Pagos

| Método | Ruta | Acceso | Caso | Descripción |
|---|---|---|---|---|
| POST | `/orders/checkout` | CLIENTE | CU-24 | Checkout con snapshot inmutable de precios, costo de envío y deducción de stock. |
| GET | `/orders` | Autenticado | CU-25 | Historial de pedidos (propio para cliente, global para administradores). |
| GET | `/orders/{id}` | Autenticado | CU-26 | Trazabilidad y detalle del pedido con snapshot de entrega. |
| PATCH | `/orders/{id}/status` | ADMIN/VENDEDOR | CU-27 | Máquina de estados (`PENDIENTE_PAGO -> PAGADO -> PREPARANDO -> LISTO -> ENVIADO -> ENTREGADO / CANCELADO`). |
| POST | `/orders/{id}/cash-confirm` | ADMIN/VENDEDOR | CU-28 | Registro y confirmación inmediata de cobro en efectivo en tienda física. |
| POST | `/payments` | Propietario | CU-29 | Inicia intención de pago vinculada al pedido (`QR`, `TARJETA`, `TRANSFERENCIA`, `EFECTIVO`). |
| POST | `/payments/webhook` | Pasarela | CU-30 | Webhook con firma criptográfica HMAC SHA-256 e idempotencia transaccional. |
| POST | `/payments/{id}/mock-confirm` | Propietario | CU-31 | Simulador de aprobación de pago para pruebas y desarrollo local. |

## 6. Realidad Aumentada (Probador Virtual)

| Método | Ruta | Acceso | Caso | Descripción |
|---|---|---|---|---|
| GET | `/ar/products/{id}/try-on-config` | Público/Opcional | CU-32 | Cálculo de matriz dimensional textil por talla, elasticidad de tela, holgura sastrera según medidas (`user_chest`, `user_waist`, `user_height`) y assets 2D/3D. |

## 7. Inteligencia Artificial (Altair AI Stylist)

| Método | Ruta | Caso | Descripción / Capacidad Controlada |
|---|---|---|---|
| POST | `/ai/chat` | CU-33 | Asistente conversacional con contexto validado de base de datos. |
| POST | `/ai/search` | CU-34 | Búsqueda en lenguaje natural con extracción semántica y ejecución SQL segura. |
| POST | `/ai/outfits/generate` | CU-35 | Composición de outfit completo por ocasión (gala, cena, fiesta, oficina) y presupuesto. |
| POST | `/ai/outfits/complete` | CU-36 | Completado armónico de look a partir de una prenda base seleccionada. |
| POST | `/ai/cart/style-check` | CU-37 | Auditoría de coherencia y balance estilístico de las prendas en el perchero. |
| POST | `/ai/cart/value-check` | CU-38 | Optimización económica, costo por uso y comparativa objetiva de calidad vs precio. |
| POST | `/ai/recommendations/apply` | CU-39 | Aplicación directa de recomendaciones de IA en el carrito del cliente. |

### Catálogo de Herramientas de Dominio (AI Tools)
Las herramientas invocadas por Altair AI están estrictamente tipadas y acotadas:
1. `search_products`: Búsqueda de prendas reales con filtros de categoría, precio, color y talla.
2. `get_product_detail`: Ficha detallada de prenda, materiales, tallas y stock.
3. `get_my_cart`: Lectura del perchero activo del cliente (tallas, colores, precios y totales).
4. `recommend_outfit`: Armado de outfits armonizados por ocasión y presupuesto.
5. `get_trending_pieces`: Selección de piezas destacadas de alta gama (Calidad Q4/Q5).
6. `get_new_arrivals`: Novedades del catálogo con stock disponible.
7. `get_most_expensive_product`: Selección de la prenda de mayor precio y calidad disponible.
8. `get_stock`: Consulta de stock real disponible por producto o variante.
9. `find_alternatives`: Alternativas para ahorro, calidad o estilo similar.
10. `calculate_cart_totals`: Cálculo determinista de totales y líneas del carrito.
11. `compare_products`: Comparativa objetiva de precio y calidad entre prendas.
12. `get_my_orders`: Consulta de pedidos recientes y estado logístico del usuario.
13. `get_my_reservations`: Consulta de reservas activas de 48h en tienda.
14. `evaluate_garment_fit`: Cálculo de holgura en cm, caída sastrera y tensión para probador AR.

## 8. WebSockets Autenticados en Tiempo Real

| Canal | Handshake Inicial | Eventos Emitidos |
|---|---|---|
| `/ws/ai` | `{"type":"auth","token":"<JWT>"}` | `connected`, `thought`, `tool_start`, `tool_result`, `presentation`, `model_status`, `token`, `done`, `error` |
| `/ws/events` | `{"type":"auth","token":"<JWT>"}` | `reservation_created`, `reservation_updated`, `order_created`, `order_updated`, `payment_updated` |

## 9. Backoffice y Administración

Prefijo `/admin`. Protegido por roles `ADMIN` y `VENDEDOR`.

| Método | Ruta | Rol | Caso | Descripción |
|---|---|---|---|---|
| POST | `/admin/categories` | ADMIN | CU-42 | Alta de categoría comercial. |
| PUT | `/admin/categories/{id}` | ADMIN | CU-42 | Actualización de categoría comercial. |
| POST | `/admin/products` | ADMIN | CU-43 | Alta de prenda en catálogo. |
| PUT | `/admin/products/{id}` | ADMIN | CU-43 | Actualización de prenda en catálogo. |
| POST | `/admin/products/{id}/variants` | ADMIN | CU-44 | Alta de variante (talla, color, SKU, código de barras). |
| PUT | `/admin/variants/{id}` | ADMIN | CU-44 | Actualización de variante y control de stock mínimo. |
| POST | `/admin/inventory/adjustments` | ADMIN | CU-45 | Ajuste manual de stock con auditoría en `movimientos_inventario` (Kardex). |
| POST | `/admin/products/ai-draft` | ADMIN | CU-46 | Generación asistida de metadatos de producto con IA (borrador). |
| GET | `/admin/reservations` | ADMIN/VENDEDOR | CU-47 | Monitoreo global de reservas en tienda. |
| POST | `/admin/reservations/expire-due` | ADMIN | CU-48 | Disparo manual de liberación de reservas vencidas (`SKIP LOCKED`). |
| GET | `/admin/orders` | ADMIN/VENDEDOR | CU-49 | Monitoreo global de pedidos en la plataforma. |
| GET | `/admin/sales/history` | ADMIN | CU-50 | Consulta del reporte de ventas desde `vw_historial_ventas`. |
| GET | `/admin/metrics/sales-inventory` | ADMIN | CU-51 | KPIs de ventas, facturación y alertas de stock bajo. |
| GET | `/admin/metrics/ai` | ADMIN | CU-52 | Métricas de uso y rendimiento de IA desde `vw_resumen_ai`. |
| GET | `/admin/ai/runtime` | ADMIN | CU-53 | Consulta de estado, plataforma y tiempo inactivo de Gemma. |
| POST | `/admin/ai/runtime/start` | ADMIN | CU-53 | Encendido manual del runtime del modelo de IA. |
| POST | `/admin/ai/runtime/stop` | ADMIN | CU-53 | Liberación y apagado del runtime de IA. |

## 10. Diagnóstico y Salud del Sistema

| Método | Ruta | Acceso | Caso | Descripción |
|---|---|---|---|---|
| GET | `/health/live` | Público | CU-54 | Liveness check para balanceadores de carga y orquestadores. |
| GET | `/health/ready` | Público | CU-54 | Readiness check validando conectividad a PostgreSQL. |
| GET | `/health/ai` | Público | CU-54 | Verificación de disponibilidad del runtime de IA Gemma. |


- `400/422`: request invalido.
- `401`: JWT/webhook invalido.
- `403`: cuenta o rol sin permiso.
- `404`: recurso inexistente o ajeno (evita enumeracion).
- `409`: conflicto de estado, duplicado o stock insuficiente.
- `410`: reserva vencida.
- `503`: PostgreSQL/Gemma no disponible, segun endpoint.
