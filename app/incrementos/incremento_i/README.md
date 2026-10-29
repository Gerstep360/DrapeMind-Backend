# Incremento I: CU-01 a CU-10

Punto de entrada SaaS: [router.py](router.py). La implementación anterior permanece en sus paquetes de negocio para que web, móvil y los demás incrementos usen las mismas reglas.

| Caso del segundo parcial | Implementación compartida relativa a app |
| --- | --- |
| CU-01 Empresas contratantes | api/v1/endpoints/saas.py; services/saas.py; models/saas.py |
| CU-02 Planes y límites | api/v1/endpoints/saas.py; services/saas.py |
| CU-03 Suscripciones empresariales | api/v1/endpoints/saas.py; services/saas.py |
| CU-04 Consultar, contratar y cambiar plan | api/v1/endpoints/saas.py; services/saas.py; integración Stripe |
| CU-05 Iniciar sesión empresarial | modules/acceso_y_gestion_de_usuarios/cu02_iniciar_sesion_y_mantener_sesion_segura.py |
| CU-06 Usuarios, empleados y roles | modules/acceso_y_gestion_de_usuarios/cu27_gestionar_usuarios_roles_y_empleados.py |
| CU-07 Sucursales según plan | modules/sucursales_inventario_y_proveedores/cu28_gestionar_ciudades_y_sucursales.py |
| CU-08 Productos, categorías y variantes | modules/catalogo_y_comercializacion/cu29_gestionar_productos_de_ropa.py y cu30_gestionar_categorias_tallas_colores_y_variantes.py |
| CU-09 Inventario y movimientos por sucursal | modules/sucursales_inventario_y_proveedores/cu34_gestionar_inventario_por_sucursal.py y cu35_registrar_movimientos_recepcion_y_ajustes_de_inventario.py |
| CU-10 Precios, descuentos y promociones | modules/catalogo_y_comercializacion/cu29_gestionar_productos_de_ropa.py y cu36_gestionar_promociones.py |

Pruebas: tests/test_saas_incremento1.py, test_saas_catalog_operations.py, test_saas_isolation.py, test_saas_billing.py y test_saas_webhooks.py.
