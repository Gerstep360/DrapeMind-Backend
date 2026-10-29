# Verificación del Incremento II

Fecha de ejecución: 28 de octubre de 2026.

| Verificación | Resultado |
| --- | --- |
| Suite backend en Windows | 210 pruebas aprobadas; 14 omitidas: 12 requieren PostgreSQL explícito y 2 verifican enlaces simbólicos de Linux |
| PostgreSQL 18 desechable desde cero | Cadena completa de Alembic hasta 20261028_01 aplicada correctamente |
| Suite específica contra PostgreSQL real | 12 pruebas aprobadas, con usuario NOSUPERUSER NOBYPASSRLS, RLS, concurrencia e integridad transaccional |
| Suite específica del incremento en SQLite | 9 pruebas aprobadas |
| Angular | 36 pruebas aprobadas y compilación de producción para /DrapeMind/ |
| Navegador Edge | Recarga PWA sin Internet, persistencia de solicitudes, respuesta perdida, confirmación sin duplicado y aislamiento al cambiar de tienda; pantallas de 1440 y 390 px |
| Flutter | 50 pruebas aprobadas; análisis sin incidencias; reapertura real de SQLite, cambio de sesión durante un envío y vistas de 320/390 px |
| APK | 1.1.0+13, compilada en release para https://167.86.106.105/DrapeMind |

La comprobación de concurrencia envía dos solicitudes con el mismo UUID y obtiene una sola reserva. Otra prueba hace competir a dos compradores por siete unidades cada uno con stock diez: solo una reserva se confirma y la otra recibe conflicto de stock. La confirmación usa el precio actual de PostgreSQL, aunque la descarga conserve un precio anterior.

Las pruebas aisladas no envían cargos a Stripe ni consultas a NVIDIA. No se ha ejecutado una prueba manual en un teléfono físico. La suite conserva una advertencia previa de Pydantic sobre configuración de clase obsoleta.
