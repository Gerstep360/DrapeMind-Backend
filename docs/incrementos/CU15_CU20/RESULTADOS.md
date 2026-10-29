# Verificación de CU-15 a CU-20

| Comprobación | Resultado |
| --- | --- |
| Suite completa backend en Windows | 221 aprobadas; 26 omitidas: 24 corresponden a PostgreSQL explícito y 2 a enlaces simbólicos Linux |
| Suite PostgreSQL 18 con migraciones reales | 24 aprobadas, usuario sin privilegios de superadministrador ni bypass RLS |
| Pruebas específicas de caja y cambios | 11 aprobadas |
| Angular | 36 pruebas aprobadas y compilación de producción para /DrapeMind/; PWA con 69 recursos precargados |
| Edge, 1440 y 390 px | Venta offline, persistencia al recargar, comprobante provisional descargado, respuesta perdida, conciliación sin duplicado, retiro de reserva, revisión de conflicto y cambio de prendas |
| Recuperación de cambio web | Se pierde la respuesta, se recarga la página y se consulta la misma operación: un solo cambio |
| Flutter | 56 pruebas aprobadas; análisis sin incidencias; vistas de 320 y 390 px |
| APK release | 1.2.0+14 para https://167.86.106.105/DrapeMind |
| Contenido de APK | Verificadas en ARM64 las rutas /offline/operations, /offline/operations/results y /retail/reservations, el espacio Caja y reservas y la URL HTTPS del VPS |

La compilación Android se genera limpiando los binarios anteriores y conservando las APK versionadas entregadas. El lanzador verifica el contenido ARM64 para impedir que una salida antigua se etiquete como versión nueva.

Las pruebas PostgreSQL incluyen envíos simultáneos de la misma venta: se registra un solo pedido, un solo pago y un único descuento de stock. También se comprueban los conflictos por precio, stock y sucursal cerrada; su anulación requiere devolución del efectivo. El cambio parcial impide devolver más unidades que las compradas y una devolución de diferencia mantiene los ingresos netos correctos.

La suite conserva una advertencia previa de Pydantic sobre configuración obsoleta. Las pruebas usan datos ficticios; no envían cargos a Stripe ni consultas a NVIDIA. No se ejecutó una prueba manual en un teléfono físico.

SHA256 de APK 1.2.0+14: bbd33cd5459864c9e45cbc07282a4d7056b38fae71628598453cd25318730263.
