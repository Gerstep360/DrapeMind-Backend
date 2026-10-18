# DrapeMind SaaS

Una aplicación Angular, una aplicación Flutter y una API FastAPI comparten PostgreSQL. Las sucursales pertenecen a una empresa; no son empresas independientes. NVIDIA continúa como único proveedor de IA.

## Planes y contratación

| Característica | Básico | Profesional |
| --- | --- | --- |
| Mensual | Bs 99 | Bs 249 |
| Anual | Bs 990 | Bs 2.490 |
| Sucursales activas | 2 | 10 |
| Productos y ventas | Sí | Sí |
| Reservas | Sí | Sí |
| Catálogo offline en móvil | Sí | Sí |
| Reportes convencionales | Sí | Sí |
| Reportes generativos con IA | No | Sí |

Los planes anual y mensual tienen las mismas funciones y capacidad. El administrador SaaS modifica límites y funciones desde `/saas-platform`; se validan en el backend. Los precios se publican en Stripe desde el panel; cambiar un precio crea otro Price ID y conserva los anteriores para contratos existentes. El checkout muestra el importe confirmado por Stripe.

La tabla de características detallada proporcionada por el usuario es la referencia: únicamente Profesional incluye reportes generativos. El PDF mencionado no estaba en el directorio de trabajo, por lo que no se afirma haber revisado sus páginas.

## Aislamiento

- `saas_tenants`, `saas_plans`, `saas_subscriptions` y las tablas de facturación forman el plano administrativo.
- Las 28 tablas comerciales incluyen `tenant_id`. Las claves foráneas compuestas impiden asociar registros de empresas distintas. Los identificadores comerciales y el correo se pueden repetir entre empresas.
- El JWT contiene `tid`, sujeto y rol. El backend verifica la pertenencia actual del usuario. `X-Tenant` identifica a la empresa al iniciar sesión o consultar contenido público; no permite cambiar la empresa de una sesión autenticada.
- `TenantSession` limita lecturas, joins, actualizaciones, borrados y relaciones. Las altas reciben la empresa de la sesión. Las consultas SQL libres están bloqueadas.
- PostgreSQL aplica `FORCE ROW LEVEL SECURITY`. El proceso HTTP usa un rol distinto del dueño de las tablas, sin `SUPERUSER` ni `BYPASSRLS`. Sin contexto, una consulta comercial no devuelve registros. El arranque rechaza un rol que omita RLS.
- La cuenta de plataforma tiene `tenant_id=NULL` y acceso al panel administrativo. No puede entrar al catálogo privado como si fuera un empleado de una empresa.
- WebSockets, notificaciones, conversaciones, herramientas de IA, perfil, pedidos, pagos y métricas conservan el contexto de empresa. El backend nunca delega el aislamiento al modelo NVIDIA.

Una cuenta pertenece a una sola empresa. Puede haber cuentas con el mismo correo en empresas diferentes. Los clientes que compren en varias empresas usan su cuenta correspondiente en cada una.

## Suscripciones y límites

Se guardan plan, inicio, vencimiento, estado y origen. Las empresas nuevas empiezan pendientes, con acceso al panel de suscripción para contratar. Si vence o se suspende el acceso, las operaciones comerciales responden `402` y se conservan los datos. Una función excluida del plan responde `403`.

El conteo se realiza sobre sucursales activas. Un bloqueo de fila por empresa y un trigger PostgreSQL evitan superar el límite incluso con solicitudes simultáneas. Para bajar de plan hay que desactivar las sucursales excedentes. Si un cambio externo en Stripe incumple el límite, el estado queda `LIMIT_EXCEEDED`; no se borran sucursales.

El administrador de plataforma puede asignar o renovar licencias administrativas con fechas. Esa acción no registra un pago Stripe. Las suscripciones vinculadas a Stripe se gestionan mediante su portal y no se sobrescriben desde el formulario administrativo. Suspender el acceso de una empresa no cancela su facturación en Stripe.

## Stripe

FastAPI crea Checkout con el Customer y Price ID guardados en el servidor. El navegador y Flutter no envían importes ni secretos. La URL de retorno no acredita un pago. Los eventos se verifican con el cuerpo original, firma y tolerancia temporal; se deduplican y se recupera el estado actual de la suscripción para soportar entregas desordenadas.

`POST /api/v1/saas/sync` recupera la suscripción propia desde Stripe. Si se completó un checkout y se perdió el webhook, consulta la sesión guardada, verifica Customer, metadatos y empresa y sincroniza la suscripción real. No crea otro checkout ni otro cobro. “Actualizar estado” y el retorno a la pantalla de suscripción usan esta recuperación. Una factura pendiente no habilita una mejora de plan.

La integración admite la versión Stripe actual, donde el estado pagado de una factura se obtiene mediante `status=paid`, además del campo `paid` de versiones anteriores.

Referencias oficiales: [Checkout para suscripciones](https://docs.stripe.com/payments/checkout/build-subscriptions), [webhooks de suscripción](https://docs.stripe.com/billing/subscriptions/webhooks), [Stripe CLI y API keys](https://github.com/stripe/stripe-cli/wiki/using-stripe-api-keys).

### Ejecución local

Desde `backend`, con el entorno virtual activo:

```powershell
python -m scripts.saas_setup backup
python -m alembic upgrade head
python -m scripts.saas_setup runtime-role
python -m scripts.saas_setup demo
python -m scripts.saas_setup stripe-prices
python -m scripts.stripe_local configure
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

En otra terminal:

```powershell
python -m scripts.stripe_local listen --port 8000
```

También están los botones del panel `python iniciar_local.py`. `configure` instala Stripe CLI oficial en `.tools`, verifica su checksum y guarda el secreto de firma local sin mostrarlo. Reinicia FastAPI después de configurarlo. `listen` requiere una clave de prueba; no cambia el endpoint publicado ni crea cobros. Mantén el reenvío abierto mientras pruebas pagos locales.

Variables privadas en `.env`:

| Variable | Uso |
| --- | --- |
| `DATABASE_URL` o `POSTGRES_*` | Conexión administrativa para Alembic y configuración del rol |
| `RUNTIME_DATABASE_URL` | Conexión restringida que utiliza FastAPI |
| `STRIPE_SECRET_KEY` | Credencial privada del mismo entorno que sus precios y Customers |
| `STRIPE_PUBLISHABLE_KEY` | Clave pública para compras; el SaaS usa Checkout alojado |
| `STRIPE_WEBHOOK_SECRET` | Firma del endpoint publicado de compras |
| `STRIPE_SAAS_WEBHOOK_SECRET` | Firma del endpoint SaaS; en local la genera Stripe CLI |
| `STRIPE_LOCAL_WEBHOOK_SECRET` | Firma del reenvío local unificado para suscripciones y pagos de prendas |
| `SAAS_WEB_URL` | URL web completa, por defecto `http://localhost:4200` |

El secreto del endpoint en Dashboard y el de Stripe CLI son distintos. No se reemplaza uno por el otro. El endpoint SaaS publicado es `/api/v1/saas/stripe-webhook`; el de compras `/api/v1/payments/stripe-webhook` también reconoce eventos SaaS. En producción, la URL debe ser pública, tener HTTPS válido y llegar a FastAPI. El endpoint registrado `https://167.86.106.105/DrapeMind/api/v1/payments/stripe-webhook` respondió **404** a GET y POST durante esta revisión; el reenvío local ya recibió eventos Stripe con respuesta 200. No se desplegaron cambios en ese servidor.

El reenvío CLI utiliza `/api/v1/payments/stripe-local-webhook`, que verifica su propio secreto y procesa tanto eventos de suscripción como `payment_intent.succeeded`, cancelaciones e intentos fallidos de compras. Este endpoint se deshabilita en producción. Los eventos repetidos no generan otra notificación de aprobación. Los eventos ajenos a un pago o Customer registrado no modifican registros comerciales.

### Datos y demostración

La migración conserva los datos existentes dentro de `drapemind`. Crea los planes y una licencia de transición administrativa, sin cobrar. No revierte automáticamente porque eliminar la propiedad empresarial sería destructivo; el respaldo permite revisar una reversión en otra base.

`demo` crea idempotentemente `moda-oriente` (Básico, dos sucursales) y `urban-fit` (Profesional, tres sucursales), con administradores, catálogo e inventario independientes y marcados como demostración. Genera credenciales aleatorias en `backend/.saas-demo-credentials.json`, ignorado por Git. El archivo también contiene el acceso del administrador de plataforma. No copia el catálogo de una empresa a la otra.

El seeder de catálogo acepta `--tenant identificador`, conserva por defecto `drapemind` como destino de mantenimiento y respeta la capacidad contratada. El reset global y el reinicio de secuencias compartidas están deshabilitados.

Para una defensa:

1. Entrar como administrador de plataforma y consultar las empresas, planes y contratos.
2. Iniciar sesión en `moda-oriente` y comprobar su catálogo y sus dos sucursales.
3. Intentar una tercera sucursal: rechazo desde el backend. Consultar reportes IA: restricción del plan.
4. Iniciar sesión en `urban-fit`: datos diferentes y capacidad Profesional. Intentar acceder a un ID de la otra empresa: 404.
5. Cambiar el plan o las fechas mediante la licencia administrativa de una empresa demo, o contratar en Stripe de prueba. Revisar estado y vencimiento. No se usan pagos reales para la demostración.

## Móvil y funcionamiento offline

Flutter solicita el identificador de empresa antes de iniciar sesión y envía el contexto en todas las peticiones. Mi cuenta abre el plan empresarial, con selección mensual/anual y Checkout/portal externos. Al volver de Stripe actualiza el estado. Una empresa sin licencia activa entra en la pantalla de suscripción.

La caché offline guarda únicamente catálogo y disponibilidad ya consultados, separada por empresa, usuario y recurso. Exige un JWT vigente y una licencia guardada con función offline activa y fecha futura. Otra cuenta no puede leer esa caché. La interfaz indica que precios y stock deben confirmarse al reconectar. Pagos, ventas y modificaciones de stock requieren conexión; no se implementó una cola de ventas offline.

## Verificación

```powershell
python -m pytest -q
python -m scripts.diagnostics.check_saas
```

Pruebas herméticas: aislamiento HTTP/ORM, identidad, relaciones, límites, vencimiento, reportes, eventos, recuperación de checkout completado, factura pagada, duplicados y orden de eventos. El diagnóstico adicional comprueba PostgreSQL real y su rol sin bypass. Las pruebas unitarias no consumen NVIDIA ni crean pagos.

Web: `npm test -- --watch=false` y `npm run build`. Móvil: `flutter analyze` y `flutter test`; la pantalla de suscripción se verifica a 320 y 390 px, con captura de referencia en `mobile/test/goldens/saas_billing_390.png`. No hubo un navegador disponible para inspección visual de la web.

Los casos existentes se mantienen. Las funciones nuevas se documentan como SaaS-01 Empresas, SaaS-02 Planes, SaaS-03 Suscripciones y SaaS-04 Consulta de contrato; no se reutiliza CU-41, ya ocupado por notificaciones en este repositorio.
