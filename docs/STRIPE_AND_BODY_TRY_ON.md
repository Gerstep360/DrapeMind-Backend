# Stripe y prueba corporal móvil

## Implementación

- Un único router/servicio Stripe compartido por las rutas de pagos existentes.
- `GET /api/v1/payments/config`: proveedor (sin claves privadas).
- `POST /api/v1/payments/stripe-intent`: recibe exclusivamente `order_id`, exige propietario y pedido pendiente. Calcula el importe en centavos BOB desde `Order.total`; no convierte moneda ni acepta importes del cliente.
- Se guarda un borrador Payment antes de contactar a Stripe. Idempotencia por pedido; un reintento recupera el mismo PaymentIntent. No guarda client_secret, tarjeta ni CVC.
- Payment Element en Angular (pedidos y checkout); PaymentSheet en Flutter (checkout y pedidos pendientes). El formulario muestra el importe que Stripe va a cobrar. No confundir completar el formulario con recibir la aprobación.
- El webhook exige firma HMAC Stripe sobre el cuerpo original, tolerancia temporal de 300 segundos, coincidencia exacta del intento, pago, pedido, importe y moneda. No busca el último pago usando sólo metadata.
- Sólo `payment_intent.succeeded` confirma con la máquina de estados existente. Un intento de tarjeta fallido sigue siendo reintentable; cancelar el PaymentIntent lo rechaza. Eventos ajenos se ignoran. Reembolsos/conciliación no se automatizan en este cambio.
- El contrato `GET /payments/order/{id}` sigue siendo una lista. Las consultas de estado no crean cobros.
- Las rutas mock no aceptan pagos Stripe ni funcionan en producción. El webhook genérico tampoco puede aprobarlos.

## Configuración de Stripe (manual, no incluida en Git)

```dotenv
PAYMENT_PROVIDER="stripe"
STRIPE_SECRET_KEY=""
STRIPE_PUBLISHABLE_KEY=""
STRIPE_WEBHOOK_SECRET=""
```

Completar con claves de la misma cuenta/modo. El instalador agrega variables faltantes pero preserva las existentes y ya no restablece el proveedor a mock. Reiniciar backend después de cambiar configuración. No pegar claves privadas en el frontend, repositorio ni chat.

Configurar el webhook de esa cuenta en `/DrapeMind/api/v1/payments/stripe-webhook`, con HTTPS/certificado válido. Suscribir `payment_intent.succeeded` y `payment_intent.canceled`. Stripe debe aceptar BOB para la cuenta; no se cambia a USD silenciosamente. Probar primero en modo test de Stripe. No se contactó ningún VPS ni se realizó ningún cargo durante el desarrollo.

Si un pedido se cancela mientras su pago externo sigue en curso, la máquina de estados rechaza una aprobación incompatible y requiere conciliación. No forzar PAGADO ni regenerar pedidos para resolver esa situación. Un flujo administrativo de reembolso sigue pendiente.

Referencias: [PaymentIntents](https://docs.stripe.com/payments/payment-intents), [firmas de webhooks](https://docs.stripe.com/webhooks), [Flutter Stripe](https://pub.dev/packages/flutter_stripe).

## Prenda corporal de prueba

En el vestidor móvil: **Escanear cuerpo · probar polera Studio** (también disponible desde el icono de la barra superior).

La pantalla nueva usa ML Kit Pose Detection en modo stream, local al teléfono. Reconoce hombros y caderas; exige confianza y cuatro detecciones consecutivas. La polera vectorial Studio se deforma según esos cuatro anclajes, con suavizado entre detecciones. No se superpone en una posición fija. Si se pierde el cuerpo, desaparece; un watchdog descarta poses antiguas. Procesa como máximo un frame cada 100 ms y nunca hace inferencias simultáneas.

El flujo libera la cámara al salir/pausar y permite cámara frontal/trasera. Incluye conversión YUV a NV21 respetando stride en Android y BGRA en iOS. La vista conserva la proporción de la cámara, sin un recorte independiente del dibujo.

**Límite explícito:** es AR 2D con seguimiento corporal, no malla corporal 3D, simulación física textil, oclusión de brazos ni medición en centímetros. La polera es una prenda de demostración identificada como tal, no un producto ficticio en stock. Las fotos del catálogo no se convierten automáticamente en prendas adaptables: necesitarán assets y anclajes adecuados. El vestidor manual anterior permanece separado.

Requisitos: Android con cámara y SDK de compilación 36; iOS mínimo 15.5, compilar en macOS con Xcode/CocoaPods. Se fijó Flutter Stripe 12.0.2 y sus paquetes nativos compatibles con Dart 3.8.1. No es necesario cambiar los modelos del VPS: la detección no usa Scout ni Gemma y no sube imágenes.

[ML Kit Pose Detection para Flutter](https://pub.dev/packages/google_mlkit_pose_detection).

## Validación y pruebas que faltan

Verificado localmente el 12/09/2026: 30 pruebas pytest del backend, 4 pruebas de geometría Flutter, análisis estático sin incidencias en vestidor/checkout/servicio de pagos, build Angular development y APK Android debug. El APK queda en `mobile/build/app/outputs/flutter-apk/app-debug.apk`. No se compiló iOS en este entorno Windows ni se probó cámara física o Stripe con una cuenta real.

Pruebas locales: firma ausente/incorrecta/caducada, rotación de firmas, rechazo de importe externo, validación del importe/moneda/metadata, selección exacta de pago, reutilización del intento; geometría, escaneo y pérdida de seguimiento.

La inspección automatizada de navegador falló por un error ACL del entorno. Compilar o pasar pruebas unitarias **no valida** el tracking real ni un cobro real. Antes de publicar:

1. Instalar APK en un teléfono, conceder/denegar permiso, pausar/reabrir, cambiar cámara.
2. Encuadrar una persona de frente con hombros/caderas visibles; comprobar alineación, desplazamiento e inclinación. Salir de cuadro: la prenda debe desaparecer. Probar cámaras/dispositivos distintos y poca luz.
3. Stripe test: éxito, tarjeta rechazada, 3DS, cancelación, reabrir pedido y evento duplicado. Confirmar que sólo el webhook cambia a PAGADO y nunca se descuenta inventario dos veces.
4. Verificar HTTPS y claves/moneda soportadas de la cuenta antes de pagos reales.
