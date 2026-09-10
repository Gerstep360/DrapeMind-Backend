# Sesión JWT y conversación: errores distintos

El login 200 y el posterior 404 en owned_session muestran que el token nuevo
funcionaba, pero el cliente enviaba un chat inexistente/cerrado/no propio.
El servidor mantiene la validación de propiedad y devuelve CHAT_NOT_FOUND.
La web descarta ese ID sin reintentar automáticamente la consulta.

Web renueva mediante el endpoint /auth/refresh ya existente antes de la caducidad.
Solo se renuevan tokens aún válidos; no se extiende la confianza en tokens vencidos.
Si la pestaña permanece suspendida más allá de su vigencia, habrá que iniciar sesión.
Un fallo transitorio de red no cierra por sí solo una sesión todavía válida.

Callbacks obsoletos de WebSocket y respuestas HTTP de un token anterior no pueden
cerrar una sesión recién iniciada. Chats locales se separan por usuario y API.
El almacén global antiguo se conserva en localStorage, pero no se importa porque
no tiene propietario verificable; no se borran conversaciones del servidor.

El instalador preserva algoritmo JWT y duración configurados. La clave existente
ya se conservaba salvo ausencia/placeholder; estos logs no prueban una rotación.
Cambiar intencionalmente SECRET_KEY revoca tokens anteriores y exige nuevo login.

Revisión estática solamente, sin pruebas, builds o inferencias por restricción previa.
