# Arquitectura de IA · DrapeMind

Angular y Flutter consumen FastAPI por HTTP y un WebSocket autenticado para el chat. FastAPI ejecuta el backend y PostgreSQL en local; la inferencia se realiza exclusivamente con NVIDIA API y requiere Internet.

## Configuración

En `backend/.env`: `NVIDIA_BASE_URL=https://integrate.api.nvidia.com/v1`, `NVIDIA_API_KEY` y `NVIDIA_MODEL`. El modelo debe estar habilitado para la cuenta y soportar streaming y herramientas. `python -m scripts.local_tasks check-ai` verifica ambos contratos con una petición real. No se descarga ni se inicia ningún proceso de inferencia en la computadora.

Modelo predeterminado verificado: `nvidia/nemotron-3-super-120b-a12b`. `python -m scripts.diagnostics.check_grounded_chat` contrasta las respuestas con el catálogo local y comprueba la separación entre texto y tarjetas. `probe_nvidia_catalog --model ...` permite medir otro modelo en un proceso de prueba sin alterar `.env`.

## Flujo

1. `concurrent_chat.py` autentica el socket y administra hasta tres tareas de conversación simultáneas, con cancelación e identificadores de petición. Cada tarea usa su propia sesión de base de datos.
2. `ai.py` reúne perfil y conversación persistida; `nvidia_agent.py` ejecuta el ciclo nativo de herramientas.
3. `llm_provider.py` admite JSON y SSE en `/chat/completions`. La selección inicial de herramientas usa JSON y las rondas posteriores admiten SSE con argumentos fragmentados. El agente retiene el texto hasta validarlo; el cliente recibe actividad real de herramientas y la respuesta pública verificada, sin razonamiento privado ni importes sin comprobar.
4. El dispatcher valida parámetros y permisos. Las consultas SQL son parametrizadas y sólo acceden al ámbito permitido del usuario.
5. Consultar productos no muestra tarjetas automáticamente. La herramienta de catálogo puede elegir `presentation=text` o `cards` y terminar en una sola inferencia con datos de PostgreSQL; `continue` permite reunir más evidencia. `respond_with_products` finaliza selecciones de varios pasos con IDs observados en el turno. `respond_with_store_data` presenta totales, sucursales, pedidos y políticas mediante plantillas del servidor. Los clientes renderizan componentes conocidos.
6. Agregar al carrito requiere un botón o petición explícita del cliente. La API vuelve a validar la variante, el precio y el stock. El modelo no ejecuta escrituras automáticamente.

La memoria del chat y las interacciones se guardan en PostgreSQL. Los errores del proveedor se comunican como errores, sin generar respuestas ficticias. Los límites de tiempo y llamadas de herramientas se configuran en `app/core/config.py`.

## Perfil inicial

Guardar las preferencias persiste primero el perfil. Con `infer_style=true`, se pide a NVIDIA una breve lectura del estilo basada en esas preferencias. La interfaz muestra el resultado real o permite reintentar si la inferencia falla, conservando los datos guardados.

## Desarrollo local

Ejecuta `python backend/iniciar_local.py`. El panel ofrece preparación del entorno, conexión/creación de DB, migraciones, seeder, comprobación NVIDIA e inicio/parada del backend. Sólo detiene el proceso que lanzó. El seeder no reinicia datos salvo que se seleccione explícitamente esa opción.

Angular: `cd web` y `npm start`. Flutter Android: `flutter run --dart-define=DRAPEMIND_API_URL=http://10.0.2.2:8000` (un dispositivo físico necesita la IP LAN de la computadora y el backend escuchando en `0.0.0.0`).

Los clientes muestran catálogo, favoritos, selección de talla/color y carrito. Altair es una ayuda opcional; los controles de proveedor y diagnósticos se reservan para administración.
