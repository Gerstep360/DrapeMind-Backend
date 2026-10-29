# Incremento II — CU-15 a CU-20

Esta ampliación pertenece al segundo incremento del segundo parcial. CU-11 a CU-14 continúan en el mismo módulo. Los identificadores históricos de los paquetes del primer parcial no se renumeran.

| Caso | Actor | Canal | Acceso |
| --- | --- | --- | --- |
| CU-15 Registrar ventas de contado sin conexión | Cajero | PWA / Flutter | Caja y reservas → Nueva venta |
| CU-16 Consultar pendientes y resultados | Cajero / Encargado / Cliente autorizado | PWA / Flutter | Operaciones y resultados; solicitudes del cliente |
| CU-17 Sincronizar reservas y ventas pendientes | Usuario autorizado | PWA / Flutter | Sincronizar y consultar resultados; recuperación automática al conectar |
| CU-18 Gestionar rechazos y conflictos | Encargado / Administrador | Web | Operaciones por revisar |
| CU-19 Atender reservas y convertirlas en ventas presenciales | Cajero / Encargado | PWA / Flutter | Caja y reservas → Atender reservas |
| CU-20 Gestionar cambios de prendas | Cajero / Encargado | Web | Cambios de prendas |

## Organización funcional

Backend: backend/app/incrementos/incremento_ii. Los casos CU-15 a CU-19 comparten un registro de sincronización y las reglas de caja de retail_service.py; CU-20 tiene cu20_cambios.py. Modelos y contratos están en models.py y schemas.py; router.py registra las rutas.

Web: web/src/app/incrementos/incremento-ii/caja, conflictos y cambios. La persistencia y sincronización compartidas permanecen en offline.

Flutter: mobile/lib/incrementos/incremento_ii/caja y offline. La caja se abre según el rol autenticado; no hay un selector para atribuirse permisos.

La autenticación, suscripciones e inventario se reutilizan. La actualización incluye Alembic 20261028_02 y mantiene PostgreSQL compartido con tenant_id, claves compuestas y RLS en las cuatro tablas nuevas.

## Reglas verificables

1. La operación se guarda en IndexedDB/SQLite antes de enviarse. Conservará el UUID, el contenido, los precios y las cantidades al reintentarse.
2. Una venta de contado registra el dinero recibido y calcula el cambio. El comprobante local es provisional; la confirmación y el comprobante de la empresa aparecen después de validar el servidor.
3. El servidor valida rol, suscripción, empresa, sucursal, precios, cantidades y stock. Pedido, pago, movimientos y resultado confirmado se conservan en la misma transacción.
4. Un conflicto válido se registra sin descontar inventario ni dejar pagos o pedidos parciales. Los problemas de acceso conservan el pendiente local.
5. Una respuesta perdida se comprueba mediante resultados por UUID. Nunca se crea otro cobro para averiguar qué ocurrió con el anterior.
6. Los resultados de cada usuario están separados por servidor, tenant y cuenta. El encargado ve conflictos de las sucursales que tiene asignadas; el administrador administra su empresa.
7. La revisión registra autor, fecha, motivo y decisión. Aceptar el precio cobrado requiere una autorización explícita. No permite forzar inventario negativo.
8. Anular una venta en conflicto requiere confirmar que se devolvió el efectivo. Las ventas cobradas no se borran como una solicitud local de reserva.
9. El retiro valida la reserva completa, vigencia y sucursal. Consume stock total y reservado una sola vez y vincula al comprador original y al empleado que atendió.
10. El cambio de prendas usa un comprobante pagado y entregado. Impide devolver más unidades de las compradas, aplica el crédito realmente pagado, registra prendas nuevas y calcula la diferencia.
11. El cambio requiere conexión. Su solicitud queda guardada si se pierde la respuesta para consultar el mismo UUID al reabrir la página.
12. El crédito de un cambio se distingue del efectivo nuevo. Las devoluciones de diferencia se registran y los indicadores de ingresos netos no duplican el crédito.

La preparación de reservas y los cambios de prendas requieren conexión. La descarga y sesión deben estar vigentes para iniciar operaciones offline; las solicitudes ya guardadas se conservan al caducar y se recuperan al volver a iniciar sesión.

## Contratos principales

- GET /offline/bundle: catálogo, sucursales autorizadas y reservas activas del personal.
- POST /offline/operations: tipo RESERVATION, SALE o PICKUP y contenido validado.
- GET /offline/operations: resultados recientes del propietario, con paginación.
- POST /offline/operations/results: consulta por hasta 100 UUID propios.
- POST /offline/operations/{uuid}/cancel: cancelación de una reserva en conflicto por su titular.
- GET /retail/conflicts; POST /retail/operations/{id}/resolve; GET /retail/operations/{id}/audit.
- GET /retail/reservations; POST /retail/reservations/{id}/prepare.
- GET /retail/orders/find; POST /retail/exchanges?preview=true; POST /retail/exchanges.

## Evidencias

Backend: tests/test_saas_incremento_ii_retail.py y tests/test_saas_incremento_ii_postgres.py. Web: scripts/check-incremento-ii.cjs y qa/incremento-ii/vps-path/cu15-cu20. Flutter: test/incremento_ii_retail_test.dart y qa/incremento-ii/retail-320.png / retail-390.png.

Las pruebas usan datos ficticios y PostgreSQL desechable para validar concurrencia y RLS. No hacen cargos a Stripe ni consultas a NVIDIA. La APK se compila para https://167.86.106.105/DrapeMind; la prueba manual en un teléfono físico se distingue de las pruebas automatizadas.
