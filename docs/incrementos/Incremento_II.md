# Incremento II — Proveedores y operación sin conexión

Entrega funcional del segundo parcial. CU-01 a CU-10 continúan en Incremento I; CU-11 a CU-14 pertenecen a este incremento. La numeración histórica de los paquetes del primer parcial conserva su significado original.

## Organización del código

| Proyecto | Incremento I | Incremento II |
| --- | --- | --- |
| Backend | backend/app/incrementos/incremento_i | backend/app/incrementos/incremento_ii |
| Angular | web/src/app/incrementos/incremento-i | web/src/app/incrementos/incremento-ii |
| Flutter | mobile/lib/incrementos/incremento_i | mobile/lib/incrementos/incremento_ii |

Cada carpeta tiene un README con sus casos, rutas y código compartido. Backend y Angular registran los incrementos mediante sus respectivos router.py/routes.ts. Autenticación, empresas, suscripciones, catálogo e inventario permanecen como servicios de dominio compartidos. Los CU anteriores reutilizan su implementación existente, con su ubicación identificada en el índice de Incremento I.

## Alcance implementado

| Caso | Canal | Funciones |
| --- | --- | --- |
| CU-11 Gestionar proveedores y abastecimiento | Web | Registrar/editar/desactivar proveedores, crear acceso autorizado, gestionar ofertas, solicitar pedidos con varias líneas, confirmar, cancelar y recibir en una sucursal |
| CU-12 Descargar catálogo y datos para operar offline | PWA / Flutter | Descargar productos, precios, categorías, variantes, sucursales autorizadas y disponibilidad; guardar la primera fotografía cuando puede descargarse |
| CU-13 Consultar catálogo, variantes y disponibilidad offline | PWA / Flutter | Consultar copia local con búsqueda por nombre, talla, color y sucursal; identificar fecha de actualización y vigencia |
| CU-14 Registrar reservas de prendas sin conexión | PWA / Flutter | Guardar solicitud durable, seguir sus estados, enviar al conectar, reintentar de forma idempotente y consultar la reserva/QR después de la confirmación |

## Reglas de operación

- El servidor obtiene empresa y usuario de la sesión autenticada. El proveedor solo puede operar sobre sus propias ofertas y pedidos; solo la administración registra recepciones.
- Una recepción incrementa el stock de la sucursal y genera movimientos de inventario una sola vez. Confirmar descuenta unidades del proveedor; cancelar un pedido confirmado las devuelve.
- Una solicitud local es pendiente. No garantiza disponibilidad ni crea un QR. Al sincronizar, FastAPI comprueba suscripción, permisos, sucursal, productos, stock real y precios actuales dentro de una transacción.
- Cada operación tiene un UUID persistente. Un reintento conserva ese UUID. Si se pierde la respuesta, el dispositivo comprueba la misma operación; no la descarta como si nunca se hubiera enviado.
- La copia local se separa por servidor, empresa y usuario. Cambiar de tienda o cerrar sesión limpia la vista y conserva las solicitudes pendientes bajo su propietario original.
- IndexedDB almacena los datos en la PWA; SQLite en Flutter. Las fotografías públicas se guardan en CacheStorage/SQLite. No se copian contraseñas, tarjetas ni domicilios de clientes.
- La descarga vence como máximo en 24 horas o al vencer la suscripción. La disponibilidad local es una referencia fechada; la comprobación final siempre ocurre en el servidor.

## Código y datos

Backend: cu11_proveedores.py, cu12_cu14_offline.py, schemas.py, models.py y common.py, dentro del Incremento II. API: /api/v1/supply y /api/v1/offline.

Angular: cu11-abastecimiento y offline dentro del Incremento II. Rutas: /suppliers-admin y /offline. La PWA requiere una compilación de producción servida por HTTPS o localhost; ng serve no instala el trabajador offline.

Flutter: offline y proveedor_web_screen.dart dentro del Incremento II. El rol proveedor usa el portal Web conforme al canal de CU-11; no entra a la tienda como cliente. La APK se compila para https://167.86.106.105/DrapeMind.

Migración Alembic: 20261028_01. Tablas nuevas: abastecimiento_pedidos, abastecimiento_items y offline_reservas_recibidas, con tenant_id, integridad por empresa, RLS y claves de idempotencia.

## Validación reproducible

- Backend: python -m pytest -q.
- PostgreSQL aislado: aplicar migraciones a una base desechable llamada incremento_ii_test; configurar INCREMENTO_II_TEST_DATABASE_URL; ejecutar python -m pytest tests/test_saas_incremento_ii_postgres.py -q. El comprobador rechaza otros nombres de base de datos.
- Angular: npm test -- --watch=false y npm run build:prod.
- Navegador: node scripts/check-incremento-ii.cjs con Playwright y Edge disponibles. Evidencias en web/qa/incremento-ii.
- Flutter: flutter analyze --no-pub y flutter test. Evidencias de 320/390 px en mobile/qa/incremento-ii; las capturas cargan Roboto y los iconos del SDK con el tema real de la aplicación.

Las pruebas de navegador usan datos ficticios. Las pruebas de PostgreSQL verifican migración real, RLS con usuario limitado, reintentos simultáneos y competencia por stock. Esto no sustituye una prueba manual en un teléfono físico.
