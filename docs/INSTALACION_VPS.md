# Instalar y mantener DrapeMind en el VPS

Destino: `/root/app/DrapeMind`. Origen público: `https://167.86.106.105`. La web abre en **https://167.86.106.105/DrapeMind/** y la API en `/DrapeMind/api/v1`, con WebSockets en el mismo origen. El prefijo permite compartir la IP con taji, CodeLingo y Gerstep sin sustituir sus páginas.

## Preparar la primera instalación

Primero publica los cambios del instalador en ambos repositorios. El lanzador descarga las ramas `Main` de `Gerstep360/DrapeMind-Backend` y `Gerstep360/DrapeMind-web`. No descarga cambios locales sin publicar. Para otras ramas usa `--backend-branch` y `--web-branch` en la primera ejecución. Para repositorios privados configura una clave SSH/gestor Git del servidor; no pongas tokens en las URL.

Copia el archivo **`backend/instalar_vps.py`**, que no necesita paquetes Python adicionales, al servidor y ejecuta:

```bash
mkdir -p /root/app/DrapeMind
cd /root/app/DrapeMind
python3 instalar_vps.py
```

Elige **Instalar desde cero**. El menú inicial también puede preparar los repositorios y abrir el gestor, actualizar o revisar el estado. La instalación desde cero prepara una aplicación nueva; no significa borrar una base existente.

Para preparar solo las descargas y los accesos al gestor:

```bash
python3 instalar_vps.py --prepare-only --yes
bash /root/app/DrapeMind/install.sh
```

Los repositorios quedan en `backend/` y `web/`. Se reconocen también los nombres antiguos `DrapeMind-Backend` y `DrapeMind-web`; no se mueven ni se duplican. `deploy.json` guarda las rutas, ramas, puerto y origen elegidos. Los lanzadores `install.sh` y `config.sh` abren el mismo gestor del backend. Los lanzadores anteriores se respaldan antes de sustituirlos.

## Qué hace la instalación nativa

1. Instala paquetes Ubuntu/Debian, PostgreSQL y Nginx. Requiere Python 3.11 o superior; Ubuntu 24.04 utiliza Python 3.12.
2. Crea `backend/.env` con secretos aleatorios y configuración de producción. Si ya existe, conserva DB, JWT, NVIDIA, Stripe y otras credenciales; actualiza origen, prefijo y CORS al destino configurado. Los secretos de plantilla se reemplazan solo cuando son marcadores reconocidos.
3. Prepara `.venv` e instala los requisitos del backend.
4. Crea, si faltan, la base `drapemind_db`, el dueño `drapemind_owner` y el rol HTTP `drapemind_runtime`. No cambia contraseñas de roles existentes. Una discrepancia se informa y detiene el proceso. El aprovisionamiento automático es para PostgreSQL local.
5. Respalda antes de migrar, ejecuta Alembic y concede permisos al runtime sin `SUPERUSER` ni `BYPASSRLS`.
6. Crea un administrador SaaS inicial solo si no existe uno. Su acceso aleatorio queda en `/root/app/DrapeMind/.deploy/admin-access.json`, legible solo por root; no aparece en logs públicos ni en el frontend.
7. Configura `drapemind-backend.service`, escuchando en `127.0.0.1:8045`. El proceso usa el usuario Linux `drapemind`; las ACL permiten atravesar `/root` y leer su aplicación sin abrir `/root` a todos. Solo sus logs y archivos estáticos necesitan escritura.
8. Descarga Node 24 en `/opt/drapemind/node/`, verifica SHA-256, ejecuta `npm ci --engine-strict` y compila Angular con el prefijo configurado. No altera el Node global ni modifica Angular para omitir sus requisitos.
9. Publica en `/var/www/drapemind/releases/…` y cambia atómicamente el enlace `current`. Conserva `previous` y las versiones anteriores. Un build fallido no cambia la web publicada.
10. Añade un snippet de rutas DrapeMind al servidor Nginx cuyo `server_name` coincide con la IP. Conserva las rutas y certificados existentes. Respalda cada archivo, ejecuta `nginx -t` y restaura la configuración si la validación o la recarga fallan.
11. Reutiliza HTTPS válido. Comprueba backend/DB, configuración web, certificado y proxy API; un fallo devuelve salida distinta de cero.

La migración SaaS se corrigió para poder instalar con el dueño de PostgreSQL sin privilegios de superusuario: utiliza el contexto administrativo únicamente dentro de su transacción al validar las claves compuestas después de activar RLS. No cambia el contexto de las conexiones HTTP.

## Menú y operaciones habituales

```bash
cd /root/app/DrapeMind
bash install.sh                 # menú interactivo
bash install.sh --all           # instalación completa
bash install.sh --update        # actualizar ambos repositorios
bash install.sh --env           # introducir NVIDIA/Stripe de forma privada
bash install.sh --migrate       # respaldo + Alembic + permisos + reinicio
bash install.sh --backup        # pg_dump, formato custom
bash install.sh --seed --quick --tenant drapemind
bash install.sh --frontend      # compilar y publicar el checkout web actual
bash install.sh --nginx         # integrar y validar proxy
bash install.sh --tls           # comprobar o preparar HTTPS
bash install.sh --restart
bash install.sh --check
bash install.sh --logs
```

`--backend` prepara únicamente el backend del checkout actual. `backend/install.sh --all` conserva ese comportamiento. `--uninstall` retira solo el servicio de DrapeMind, conservando código, datos y web. `--notify` conserva el despachador existente. El reset global del seeder está bloqueado.

El menú se adapta al ancho de la terminal; cada operación vuelve al menú al finalizar. Los pasos muestran actividad animada, tiempo transcurrido y avance por etapas. Al cancelar, se señala al grupo del paso en ejecución, incluidos sus procesos hijos. Para sesiones lentas o sin animaciones:

```bash
DRAPEMIND_NO_ANIMATION=1 NO_COLOR=1 bash install.sh
```

Sin TTY la salida es texto plano. Los registros de cada paso quedan en `/var/log/drapemind/<ejecución>/`, con acceso privado. No se imprime automáticamente su contenido, que podría contener mensajes de proveedores o controladores. El diagnóstico de IA real sigue disponible en `bash backend/install.sh --check-ai`; no se ejecuta automáticamente ni consume peticiones NVIDIA durante la instalación.

## Configurar IA y pagos

Desde `python vps_terminal.py`, abre Acciones y pulsa **Subir .env de forma privada**. Copia completos los archivos locales `backend/.env` y `web/.env` por SFTP a `/root/app/DrapeMind/.private/env/backend.env` y `web.env`. Verifica SHA-256 antes de publicar cada copia y conserva la anterior cuando cambia. Las carpetas privadas tienen modo `700` y los archivos `600`; el resumen muestra estado y nombres, sin los valores.

La primera instalación importa esas copias automáticamente. Conserva todas las claves NVIDIA, Stripe y variables adicionales. La copia original permanece íntegra y privada; el archivo de ejecución ajusta origen, CORS y conexiones PostgreSQL a esta instancia. No reutiliza la contraseña PostgreSQL del PC para modificar el usuario postgres del VPS.

Si una firma publicada coincide con `STRIPE_LOCAL_WEBHOOK_SECRET`, se identifica como firma de Stripe CLI: no se activa como firma pública. Se conserva una firma publicada válida de la instancia si existía; en caso contrario queda pendiente de configurar desde Dashboard. La copia original en `.private/env` permanece intacta. El webhook unificado de compras también procesa los eventos SaaS del endpoint registrado, y el endpoint SaaS dedicado requiere su firma correspondiente.

Para actualizar las claves después de otra subida:

```bash
bash /root/app/DrapeMind/install.sh --import-env
```

En una instancia existente se conservan su conexión DB, JWT y secreto interno de pagos; se respaldan sus variables anteriores en `.deploy/env-backups` y se actualizan los proveedores desde la copia enviada. Se reinicia el backend si estaba activo. El `.env` de web queda privado en el checkout; el build publica únicamente `backendUrl` y `apiPrefix` en `config.json`, sin trasladar sus secretos a JavaScript.

Los `.env` están ignorados por Git en ambos repositorios. La conexión de `vps_terminal` lee `.vps_credentials`, ignorado localmente, o variables `DRAPEMIND_VPS_*`; su contraseña SSH ya no está escrita en `vps_core/config.py`. También puede usar clave SSH o agente cuando no hay contraseña configurada.

Abre `--env` para guardar NVIDIA_API_KEY, claves Stripe y las firmas de los webhooks publicados. Enter conserva cada valor existente. También se pueden editar las variables de correo/Firebase en `backend/.env` con un editor del servidor y reiniciar después.

No se usa el secreto de Stripe CLI como firma de producción. En Stripe Dashboard, las rutas públicas son:

- SaaS: `https://167.86.106.105/DrapeMind/api/v1/saas/stripe-webhook`.
- Compras: `https://167.86.106.105/DrapeMind/api/v1/payments/stripe-webhook`.

Sin clave NVIDIA o Stripe el gestor indica que quedan pendientes; no inventa una inferencia ni un pago de prueba. Configurar credenciales no publica precios ni crea cobros automáticamente. Los precios SaaS se administran desde el panel existente.

## Actualizaciones y recuperación

`--update` exige ambos checkouts limpios y las ramas indicadas en `deploy.json`. Comprueba el avance directo en los dos repositorios, crea un respaldo y recién después avanza Git. Si hay cambios locales o divergencia, se detiene sin descartarlos: guarda un commit o stash de manera consciente antes de reintentar. No utiliza `reset --hard`.

Después actualiza dependencias, aplica migraciones, compila la web, renueva permisos y reinicia el backend. Las operaciones se serializan con `flock`. Los respaldos PostgreSQL quedan en `backend/backups/`. Un fallo de migración detiene los pasos siguientes; no hay una reversión automática de esquema ni de datos. Revisa el registro y el respaldo antes de recuperar una base.

Para volver únicamente a la web anterior, tras revisar los enlaces:

```bash
readlink /var/www/drapemind/current
readlink /var/www/drapemind/previous
ln -s "$(readlink /var/www/drapemind/previous)" /var/www/drapemind/.restore-current
mv -Tf /var/www/drapemind/.restore-current /var/www/drapemind/current
```

Si se detectan rutas antiguas `/DrapeMind/` en Nginx, el instalador se detiene y pide retirar únicamente su snippet antiguo. No reemplaza el sitio `default` ni intenta reparar configuraciones de las otras aplicaciones.

## HTTPS desde un servidor vacío

En este VPS ya existe un certificado válido para `167.86.106.105` y se reutiliza. No se cambia su mecanismo de renovación.

En un servidor sin certificado, el gestor puede crear un sitio HTTP propio, obtener un certificado con Certbot 5.4+ y programar la renovación cada 12 horas con recarga de Nginx. Pide correo y aceptación de términos antes de emitirlo. Para automatizar esa aceptación explícita:

```bash
python3 instalar_vps.py --action install --yes --accept-acme-tos --email tu-correo@dominio.com
```

El puerto 80 debe ser accesible para el desafío HTTP-01 y el 443 para la aplicación. Si ya hay un servidor HTTP compartido sin HTTPS, debe exponer el webroot ACME antes de solicitar el certificado; no se toma su puerto con un servidor standalone. Las rutas DrapeMind redirigen HTTP a HTTPS sin cambiar las otras aplicaciones.

Let's Encrypt permite certificados para IP mediante el perfil de corta duración; Certbot requiere renovación automática y un hook para recargar el servidor. [Guía oficial de Certbot para certificados IP](https://letsencrypt.org/2026/03/11/shorter-certs-certbot).

## Comprobaciones realizadas

- Backend: 175 pruebas aprobadas en Windows, dos pruebas de symlinks omitidas allí; las 15 pruebas específicas del instalador aprobaron en Ubuntu 24.04, incluidas esas dos.
- Build Angular de producción con base `/DrapeMind/`: aprobado.
- Nginx independiente en un puerto loopback temporal: fallback SPA, config sin caché, API, salud y cabeceras de WebSocket comprobados.
- Publicación por versiones: un build fallido conserva `current`; un build válido publica la versión nueva y conserva `previous`.
- PostgreSQL real con una base y roles temporales: esquema desde cero, todas las migraciones, rol sin bypass, salud FastAPI y login del administrador inicial comprobados. Los recursos temporales de PostgreSQL se retiran al terminar.
- Panel `vps_terminal.py`: distribución de una, dos y tres columnas y envío de la instalación interactiva a la terminal comprobados.

Se usaron copias temporales y servicios de prueba; no se activó DrapeMind ni se modificó el Nginx publicado durante esta revisión. No se emitió un certificado nuevo ni se hicieron peticiones NVIDIA o cobros Stripe. La emisión ACME nueva y el flujo completo de paquetes/systemd quedan para la instalación efectiva.
