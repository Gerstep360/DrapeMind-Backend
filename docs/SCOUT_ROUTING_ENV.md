# Respuestas directas y migración de configuración

El archivo adjunto ya tiene SCOUT_ENABLED=true y los límites numéricos recientes.
El backend convertía finish a delegate por confidence ausente/inferior a 0.85.
Ahora respeta finish; la confianza autodeclarada no activa otro modelo. Scout
debe delegar explícitamente análisis complejo; charla y capacidades se responden
directamente. No se introdujeron detectores de frases ni saludos hardcodeados.
SCOUT_DIRECT_CONFIDENCE se conserva por compatibilidad pero ya no fuerza routing.

El prompt se acortó y diferencia tools de lectura de permisos de escritura.
Las sugerencias son peticiones del usuario, no preguntas del asistente. El botón
muestra el prompt que envía, también en historial web antiguo; las respuestas
nuevas exponen el mismo texto como label para otros clientes.

## Actualizaciones de .env

install.sh llama a sync_env_production y este a scripts/migrate_ai_env.py.
La fuente de defaults numéricos es .env.example, ya versionado en Git.
No es necesario mantener los mismos números duplicados en 01_env.sh.

- Variables numéricas administradas nuevas se agregan.
- Si el valor coincide con el default anterior registrado, se actualiza.
- Valores personalizados distintos se conservan y se enumeran solo sus nombres.
- En la primera adopción no existe baseline: valores distintos se conservan.
- Claves, URLs, rutas, activación Scout y razonamiento no se sobrescriben.
- Los defaults conocidos se guardan en .env.ai-defaults.json, sin secretos.
- Antes de cambiar el archivo se crea .env.before-ai-migration con permisos 0600.
- No eliminar el baseline entre actualizaciones; está excluido de Git.

Para agregar un parámetro administrado nuevo, añadirlo a MANAGED en el migrador
y a .env.example. No se evalúa ni ejecuta el contenido de .env.
Una personalización heredada puede restablecerse eliminando solo su línea del
.env activo antes de sincronizar; el migrador incorporará el default actual.

No se modificó el .env adjunto ni se ejecutó el migrador sobre producción.
No se hicieron pruebas ni inferencias. Los tiempos enviados no permiten medir
RAM total; el ahorro esperado de una llamada evitada requiere validación real.
