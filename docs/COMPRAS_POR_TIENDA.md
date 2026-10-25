# Cuenta personal y compras por tienda

El cliente entra a `https://167.86.106.105/DrapeMind/tienda/<nombre-enlace>` o elige una tienda desde `/tiendas`. En móvil puede usar `drapemind://tienda/<nombre-enlace>` o «Cambiar de tienda» en su cuenta. Una cuenta personal sirve para todas las tiendas. Al cambiar, el servidor valida la identidad, prepara su relación con la tienda y devuelve un JWT nuevo limitado a ella. El cliente nunca envía roles ni un `tenant_id` autorizado por sí mismo.

## Qué información se guarda

| Información | Propietario y ámbito |
| --- | --- |
| Correo, contraseña, nombre y teléfono personales | Identidad de cliente común |
| Preferencias declaradas y direcciones personales | Cuenta personal; disponibles al entrar a otra tienda |
| Rol de empleado, asignación a sucursales y bloqueo empresarial | Empresa correspondiente |
| Catálogo, precios, promociones y disponibilidad | Empresa y, para inventario, sucursal |
| Carrito, favoritos, reservas y pedidos | Relación del cliente con cada empresa |
| Conversaciones, recomendaciones y referencias a prendas | Tienda donde se generaron |
| Pago y comprobante | Pedido y empresa vendedores |
| Venta presencial | Empresa y sucursal; comprador y empleado se registran por separado |

El almacenamiento offline y los chats móviles usan claves por empresa y usuario. Cambiar de tienda limpia el estado visible, reconecta los eventos y descarta respuestas de otra sesión. La caché antigua de chat sin propietario no se reasigna a una cuenta.

## Alta de empresa

El panel guía por empresa, administrador y plan. El enlace se genera desde el nombre; se puede personalizar. Los errores aparecen junto a los campos. La contraseña inicial del administrador requiere 12 caracteres y se puede generar en el formulario.

Se puede elegir contratación con Stripe, que comienza pendiente, o una licencia administrativa con vencimiento futuro, sin registrar un cobro. Un contrato pendiente sin suscripción Stripe real puede activarse administrativamente. Los contratos con cobros activos se gestionan desde Stripe. Se guardan dirección, teléfono y correo comerciales opcionales para sus comprobantes.

## Compra y sucursal

En recojo, `CheckoutRequest.sucursal_id` es obligatorio. FastAPI exige que la sede pertenezca a la empresa del JWT, esté activa y tenga todas las cantidades. Para delivery se determina una sede activa capaz de preparar el pedido completo; su identificador queda guardado. No se reparten cantidades entre varias sucursales en una misma orden.

El servidor bloquea el carrito, las variantes y el stock de la sede, toma los precios actuales del catálogo y valida la compra antes de confirmarla. Descuenta `stock_sucursal` y recalcula el agregado de la variante. Una cancelación antes del pago repone la misma sede y deja su movimiento. Las reservas conservan su sucursal al convertirse en venta.

En caja, `pedidos.usuario_id` identifica al comprador registrado o queda vacío. `atendido_por_id` identifica al empleado y `comprador_registrado` distingue una compra anónima. Los tickets anteriores que guardaban al empleado como comprador se corrigen cuando su origen POS es verificable.

## Comprobantes

La identidad se consulta desde la empresa y la sucursal del pedido. No se sustituyen datos faltantes por direcciones, NIT, teléfonos ni garantías fijas de otra empresa. Si un ticket histórico carece de sede, se indica «Sucursal no registrada» y se usa únicamente el contacto comercial disponible.

Los comprobantes públicos requieren el código UUID del pedido además de su número y tienda. El QR incluye esa referencia; conocer un número correlativo no permite consultar los datos de otro comprador.

## Actualización

La migración `20261025_02` añade identidad personal, contactos comerciales, comprador opcional y empleado que atendió. No elimina pedidos, carritos ni usuarios. Las cuentas personales antiguas se vinculan al autenticar; correos coincidentes con credenciales diferentes requieren revisión y no se fusionan automáticamente. Antes de desplegar se crea y restaura un respaldo en una base temporal para comprobar la migración con RLS real.
