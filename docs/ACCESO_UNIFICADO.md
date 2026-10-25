# Acceso automático a la cuenta

Web y móvil solicitan correo y contraseña. `POST /api/v1/auth/login` valida las credenciales contra las cuentas guardadas y devuelve perfil, empresa y destino. No se envía un rol ni un indicador de administración. Los campos adicionales de privilegios se rechazan y las operaciones protegidas continúan validándose en el backend.

El backend consulta por correo mediante el índice `ix_usuarios_login_email`; conserva la unicidad de correos dentro de cada empresa. No deduce permisos por el nombre del correo ni por su dominio. Ignora tokens y cabeceras de empresa anteriores al resolver un nuevo acceso.

| Cuenta validada | Destino web | Aplicación móvil |
| --- | --- | --- |
| Administración SaaS | `/saas-platform` | Resumen de empresas y acceso a la gestión web |
| Empresa sin licencia vigente | `/subscription` | Pantalla de suscripción |
| Cliente sin perfil de estilo | `/onboarding` | Preferencias de estilo |
| Cliente con perfil | `/catalog` | Tienda |
| Cajero | `/pos` | Espacio móvil de su cuenta, con permisos del backend |
| Personal de empresa | `/dashboard` | Espacio móvil de su cuenta, con permisos del backend |

En un acceso nuevo, perfil y empresa llegan en la misma respuesta; los clientes evitan una petición `/auth/me` adicional. Para recuperar una sesión guardada se sigue consultando el perfil al servidor. El móvil conserva el token en almacenamiento seguro y usa HTTPS con la IP pública; el desarrollo local admite la URL HTTP definida para ese entorno.

## Enlaces de tienda

Cada empresa dispone del enlace `https://167.86.106.105/DrapeMind/tienda/<slug>`. La pantalla muestra el nombre de la tienda y resuelve el contexto desde ese enlace, sin pedir que se escriba un identificador. El panel SaaS permite abrir el acceso de cada empresa. Son enlaces de entrada; el resto de las rutas privadas usa el contexto de la sesión autenticada.

El móvil admite `drapemind://tienda/<slug>` y reconoce el contexto de entrada al abrir la aplicación. Si había una sesión de otra empresa, solicita el acceso correspondiente; no traslada un token a otra empresa. Android declara ese enlace de aplicación y iOS utiliza el esquema ya registrado.

Si un correo existe en varias empresas con contraseñas distintas, se identifica la cuenta que coincide. Si coincide el mismo correo y contraseña en varias, se pide abrir el enlace de su tienda. No se devuelve una lista de empresas ni se elige una arbitrariamente. Una cuenta bloqueada o una empresa inactiva no obtiene token.

## Cuenta SaaS genérica

`python -m scripts.saas_setup platform-admin` prepara la cuenta genérica `adminsaas@drapemind.com`, sin modificar las cuentas existentes ni sus contraseñas. El instalador también la prepara. Su contraseña se genera aleatoriamente y queda en `.deploy/admin-access.json`, fuera de Git y con permisos privados; el acceso anterior se conserva en el respaldo privado si el archivo ya existía. No se publican contraseñas en esta documentación.

El seeder público solo contiene cuentas genéricas. Las cuentas privadas existentes se conservan en PostgreSQL y no se recrean en cada empresa desde el catálogo de prueba.

Antes de actualizar se crea un respaldo completo, compatible con `FORCE RLS`, usando el contexto administrativo únicamente en la conexión de `pg_dump`, formato custom y registros `INSERT`. El archivo nace con permisos `600`; no se desactiva RLS ni se conceden privilegios de bypass al servicio. [Opciones oficiales de respaldo con RLS](https://www.postgresql.org/docs/current/app-pgdump.html).

## Validación

Se cubren la resolución automática, correos repetidos, contexto desde enlaces, cuentas bloqueadas, planes vencidos, destinos por rol, rechazo de privilegios enviados por el cliente y aislamiento después del acceso. Web comprueba la ausencia de selectores, la respuesta única y errores legibles. Flutter comprueba el uso de almacenamiento seguro, el contexto de tienda, la entrada SaaS y el formulario a 320/390 píxeles sin desbordamientos.
