# Roles propios y avisos de tiendas

En **Tu equipo y tus clientes**, el administrador empresarial crea perfiles reutilizables y ajusta excepciones por persona. Los administradores conservan acceso completo; la gestión del equipo no se delega. Los clientes universales conservan una membresía independiente por tienda.

`GET /team/catalog`, `GET/POST /team/roles`, `PUT /team/roles/{id}` y `GET/PUT /team/users/{id}/access` requieren administración de la empresa. `GET /team/me` y `/auth/me` entregan los permisos efectivos. Los cambios se comprueban desde PostgreSQL, sin confiar en permisos enviados por el cliente ni en roles antiguos del JWT. Las rutas privadas, las herramientas de Altair/MCP y las operaciones que se sincronizan respetan las restricciones. Los controles de sucursal y suscripción siguen activos.

La migración `20261108_01` crea `roles_empresa` y `accesos_usuario`, con claves foráneas compuestas y RLS forzado. Cambia el índice de token push a no único; la restricción por usuario y token permanece. Su reversión exige resolver previamente los tokens compartidos, sin eliminar asociaciones automáticamente.

Flutter registra exclusivamente tokens reales de Firebase. El backend los asocia a las membresías activas de la identidad autenticada. La PWA utiliza Web Push con suscripción cifrada y una clave VAPID persistente en `backend/.runtime/webpush.pem`. El instalador prepara esa carpeta privada para el servicio. Conservarla en las copias de seguridad de configuración junto con la cuenta de servicio Firebase; no publicarlas en Git. HTTPS de confianza y permiso del navegador son necesarios para activar los avisos.

`POST /notifications/send` envía un aviso a una persona activa de la empresa. La tienda de origen la asigna el servidor. Se guarda una notificación individual; la respuesta distingue aceptación por proveedores, fallos y ausencia de dispositivos. FCM no simula entregas cuando falta configuración. Un error de proyecto no invalida todos los tokens; se desactivan los que Google identifica como `UNREGISTERED`.

Al tocar un aviso de otra tienda, la cuenta universal cambia de contexto mediante `/auth/store` y abre el destino después de obtener su nuevo JWT. Las bandejas y las conexiones se reinician al cambiar de cuenta o empresa. Un empleado no cambia de empresa mediante un payload push. El token del dispositivo para sincronizar lecturas viaja en `X-Device-Token`.

Validación: 263 pruebas backend; 43 pruebas PostgreSQL con RLS; 40 Angular; 63 Flutter. Editor de roles y avisos revisado en 1440 y 390 px. Google OAuth validado con la cuenta de servicio de producción, sin enviar mensajes a clientes. La recepción en un teléfono físico requiere instalar la APK, iniciar sesión y conceder permiso de notificaciones; no se certifica recepción física con estas pruebas.

Figuras y evidencias: [paquete actualizado](entregas/Roles_y_avisos_multitienda.zip).
