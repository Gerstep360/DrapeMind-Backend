# Segundo parcial · Código por caso de uso

Este es el directorio canónico de la implementación. Cada carpeta y archivo específico identifica el CU de la numeración vigente. No se utilizan incrementos como paquetes de ejecución.

Los servicios técnicos generales permanecen en `core` o en `app/services`. `compartido` contiene contratos, persistencia y utilidades usados por varios CU. La funcionalidad compartida se implementa una sola vez: descarga (CU-12), catálogo (CU-13), captura (CU-14/CU-15/CU-19), revisión (CU-16) y sincronización (CU-17) colaboran sobre la misma cola por cuenta y tienda. Un CU no necesita una copia de esa cola ni una aplicación independiente.

La operación habitual es con conexión: catálogo, Altair, carrito, pagos y pedidos. La persistencia local complementa ese flujo cuando se pierde Internet. Los códigos de base de datos históricos se conservan únicamente para migrar y leer operaciones guardadas anteriormente.

| Código | Caso de uso | Implementación |
|---|---|---|
| CU-01 | Gestionar empresas contratantes SaaS | [cu01_empresas](cu01_empresas/) |
| CU-02 | Configurar planes y límites de suscripción | [cu02_planes](cu02_planes/) |
| CU-03 | Administrar suscripciones empresariales | [cu03_suscripciones](cu03_suscripciones/) |
| CU-04 | Consultar, contratar, renovar o cambiar plan empresarial | [cu04_plan_empresa](cu04_plan_empresa/) |
| CU-05 | Iniciar sesión y acceder a la empresa autorizada | [cu05_acceso](cu05_acceso/) |
| CU-06 | Gestionar usuarios, empleados y roles | [cu06_usuarios_roles](cu06_usuarios_roles/) |
| CU-07 | Gestionar sucursales según el plan contratado | [cu07_sucursales](cu07_sucursales/) |
| CU-08 | Gestionar productos, categorías y variantes | [cu08_productos](cu08_productos/) |
| CU-09 | Gestionar inventario y movimientos por sucursal | [cu09_inventario](cu09_inventario/) |
| CU-10 | Gestionar precios, descuentos y promociones | [cu10_precios_promociones](cu10_precios_promociones/) |
| CU-11 | Gestionar proveedores y abastecimiento | [cu11_proveedores](cu11_proveedores/) |
| CU-12 | Descargar catálogo y datos necesarios para operar offline | [cu12_descarga_offline](cu12_descarga_offline/) |
| CU-13 | Consultar catálogo, variantes y disponibilidad offline | Usa los servicios y vistas compartidos indicados abajo; no se duplica implementación. |
| CU-14 | Registrar reservas de prendas sin conexión | [cu14_reservas_offline](cu14_reservas_offline/) |
| CU-15 | Registrar ventas de contado sin conexión | [cu15_ventas_contado](cu15_ventas_contado/) |
| CU-16 | Consultar operaciones pendientes y resultados de sincronización | [cu16_operaciones_pendientes](cu16_operaciones_pendientes/) |
| CU-17 | Sincronizar reservas y ventas pendientes | [cu17_sincronizacion](cu17_sincronizacion/) |
| CU-18 | Gestionar operaciones rechazadas o en conflicto | [cu18_conflictos](cu18_conflictos/) |
| CU-19 | Atender reservas y convertirlas en ventas presenciales | [cu19_atencion_reservas](cu19_atencion_reservas/) |
| CU-20 | Gestionar cambios de prendas | [cu20_cambios](cu20_cambios/) |
| CU-21 | Generar, consultar y descargar comprobantes de venta | [cu21_comprobantes](cu21_comprobantes/) |
| CU-22 | Gestionar carrito y realizar checkout | [cu22_carrito_checkout](cu22_carrito_checkout/) |
| CU-23 | Procesar pago electrónico y confirmar pedido | [cu23_pagos](cu23_pagos/) |
| CU-24 | Consultar pedidos, entregas e historial de compras | [cu24_pedidos](cu24_pedidos/) |
| CU-25 | Generar reportes empresariales mediante lenguaje natural o voz | [cu25_reportes_voz](cu25_reportes_voz/) |
| CU-26 | Visualizar y exportar reportes empresariales en PDF o Excel | [cu26_exportar_reportes](cu26_exportar_reportes/) |
| CU-27 | Consultar dashboard de indicadores comerciales | [cu27_dashboard](cu27_dashboard/) |
| CU-28 | Consultar predicciones y patrones de Machine Learning | [cu28_machine_learning](cu28_machine_learning/) |
| CU-29 | Consultar Altair y obtener recomendaciones de prendas | [cu29_altair](cu29_altair/) |
| CU-30 | Utilizar vestidor virtual mediante realidad aumentada | [cu30_vestidor](cu30_vestidor/) |

CU-21 comparte datos y descarga del comprobante con CU-24; CU-26 exporta los reportes generados en CU-25; CU-28 usa indicadores de CU-27. Las operaciones definidas exclusivamente para web o Flutter mantienen su plataforma; no se crean archivos vacíos para aparentar una implementación adicional.

La documentación académica canónica está en `segundo parcial/Documentacion`, organizada por CU-01 a CU-30 y modelos generales. Los diagramas reflejan HTTP, permisos, tenant, persistencia y servicios reales. El backend valida todos los límites y autorizaciones aunque el cliente tenga un botón visible.

La caja presencial en línea reutilizada del primer parcial está en `compartido/caja_online`; no se confunde con CU-15, que registra ventas de contado sin conexión. CU-23 recibe confirmaciones reales de Stripe. La voz usa audio temporal revisable antes de enviar la consulta. CU-28 persiste modelos de demanda por tenant y alcance.
