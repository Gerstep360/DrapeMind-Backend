# Incremento II — CU-11 a CU-14

- `cu11_proveedores.py`: proveedores, cuentas autorizadas, ofertas y pedidos de abastecimiento. La recepción usa el inventario compartido por sucursal.
- `cu12_cu14_offline.py`: descarga de datos autorizados y confirmación transaccional de solicitudes offline. CU-13 consulta la copia local en los clientes.
- `schemas.py`: contratos de entrada con campos adicionales rechazados.
- `models.py`: pedidos, líneas de abastecimiento y recibos de operaciones idempotentes.
- `router.py`: único punto de registro de este incremento en la API.

La migración correspondiente es `20261028_01`. Las tablas incluyen pertenencia empresarial, claves compuestas y RLS forzado. Los servicios comunes de autenticación, suscripciones, catálogo e inventario conservan una sola implementación.
