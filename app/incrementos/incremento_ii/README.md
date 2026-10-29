# Incremento II — CU-11 a CU-20

- `cu11_proveedores.py`: proveedores, cuentas autorizadas, ofertas y pedidos de abastecimiento. La recepción usa el inventario compartido por sucursal.
- `cu12_cu14_offline.py`: descarga de datos autorizados y confirmación transaccional de solicitudes offline. CU-13 consulta la copia local en los clientes.
- `schemas.py`: contratos de entrada con campos adicionales rechazados.
- `models.py`: pedidos, líneas de abastecimiento y recibos de operaciones idempotentes.
- `router.py`: único punto de registro de este incremento en la API.

La migración correspondiente es `20261028_01`. Las tablas incluyen pertenencia empresarial, claves compuestas y RLS forzado. Los servicios comunes de autenticación, suscripciones, catálogo e inventario conservan una sola implementación.

## Caja, sincronización y cambios

- `cu15_cu19_operaciones.py`: CU-15, CU-16, CU-17, CU-18 y CU-19; registro de operaciones, resultados por propietario, revisión con auditoría y preparación de reservas.
- `retail_service.py`: validación de caja y sucursal, precios, inventario y conversión de reservas con cobro en efectivo.
- `cu20_cambios.py`: búsqueda del comprobante, cálculo previo y registro idempotente de cambios parciales, crédito y diferencias.
- Migración `20261028_02`: offline_operaciones, offline_operaciones_auditoria, cambios_prendas y cambios_prendas_devoluciones. Integridad por tenant y RLS forzado.
- `app/services/financials.py`: ingresos netos; excluye el crédito reutilizado y descuenta la devolución de efectivo registrada por un cambio.

La cola de reservas anterior conserva compatibilidad. La nueva API común es POST /offline/operations. Los cuerpos son inmutables y el UUID se mantiene al reintentar. Los errores de negocio válidos se guardan como CONFLICT sin pedidos, pagos ni movimientos parciales; los problemas de autenticación conservan las operaciones locales para recuperar la sesión.

CU-18 nunca permite forzar stock negativo. El encargado puede volver a validar, autorizar expresamente el precio cobrado o anular con motivo y confirmación de devolución del efectivo. El historial conserva quién tomó la decisión.
