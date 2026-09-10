# DrapeMind: Scout + Gemma bajo demanda

## Alcance

Implementación sobre FastAPI existente, sin Django, Docker, nuevas dependencias
ni descarga de modelos. No se ejecutaron pruebas, benchmarks ni inferencias de
esta arquitectura por solicitud del usuario. No se contactó al VPS.
No se afirma una latencia ni precisión todavía no medidas.

`SCOUT_ENABLED=false` conserva el agente anterior. Al activarlo, un modelo real
independiente decide las herramientas, actualiza contexto y responde directamente
o delega a Gemma. No hay clasificación por palabras clave ni fallback silencioso.

## Recorrido y reutilización

1. REST `/api/v1/ai/chat` y WebSocket `/api/v1/ws/ai` comparten `run_agent_socket`.
2. Se verifica propiedad de AISession y se carga su resumen_contexto.
3. `chat_context.py` carga restricciones/hechos, entidades ordenadas, selección y
   pregunta pendiente. No carga mensajes históricos para el modelo.
4. `scout_orchestrator.py` envía a Scout instrucciones estables, firmas del registro,
   estado, observaciones y mensaje íntegro. Valida su decisión con JSON Schema/Pydantic.
5. `ai_agent.py` reutiliza el ciclo de herramientas y construcción de tarjetas.
   `ai_tools.py` ejecuta servicios con usuario autenticado; ningún LLM accede a SQL.
6. Scout decide `tool`, `finish` o `delegate`. En finish no se carga Gemma.
7. Si delega, Gemma recibe estado, observaciones compactas y mensaje actual:
   **cero firmas de herramientas**, ningún historial ni JSON de planificación.
8. Se guardan mensajes completos en AIInteraction y estado versionado en AISession.

No hace falta una nueva columna. Un chat nuevo empieza vacío; `chat_sessions.py`
controla propiedad, selección y borrado. No existe memoria global de selecciones.
El estado antiguo incompatible se inicia vacío, sin borrar mensajes visibles.
No se añade ni mezcla un perfil permanente.

## Elegir y activar Scout

Copiar el bloque Scout de `.env.example` al `.env` del backend. El ejemplo no se
carga automáticamente. Colocar manualmente el GGUF elegido y reiniciar FastAPI:

```dotenv
SCOUT_ENABLED=true
SCOUT_MODEL="scout"
SCOUT_MODEL_PATH="ai_models/scout/archivo-elegido.gguf"
SCOUT_BASE_URL="http://127.0.0.1:8089/v1"
SCOUT_SERVER_PORT=8089
SCOUT_MANAGED_SERVER=true
SCOUT_THREADS=2
```

SCOUT_MODEL es un alias local, no una descarga. Se reutiliza LLAMA_SERVER_PATH en
Windows/Linux. El servidor debe admitir JSON Schema, la plantilla del modelo y
chat_template_kwargs. Un GGUF cualquiera no garantiza compatibilidad.

Candidato recomendado para evaluar: **Qwen3-0.6B**, GGUF, sin thinking solo para Scout.
La [ficha oficial](https://huggingface.co/Qwen/Qwen3-0.6B) documenta tamaño y modo
enable_thinking=False. No está validado en DrapeMind. No se implementa un adaptador
al protocolo nativo de FunctionGemma. La elección y descarga quedan al usuario.

Para Scout ya iniciado externamente en la misma máquina, usar
SCOUT_MANAGED_SERVER=false y el alias real. Su URL se restringe a loopback;
no compartir puerto con Gemma ni exponer los servidores públicamente.

## Recursos y procesos

- Scout: CPU, un slot, 2 threads por defecto, límite configurable de 1 a 3.
- Chat: un turno a la vez dentro del worker. Desplegar **un worker**; no es un
  bloqueo distribuido. Otros endpoints especializados no comparten esta cola.
- Scout y Gemma hacen inferencia secuencial en el circuito nuevo.
- Scout se carga bajo demanda y descarga tras 300 segundos inactivo.
  Gemma conserva su configuración. Ambos pueden permanecer residentes durante
  sus períodos de inactividad: revisar RAM antes de dejar ambos activos en el VPS.
- Cada runtime administra solo su propio proceso. Se quitaron pkill/taskkill
  globales que podían cerrar el otro modelo. Procesos externos no se terminan.
- Logs separados: logs/llama-server.log y logs/llama-scout.log.
- Ejemplo Gemma: CPU, contexto 4096, threads 3, slot 1, razonamiento 64.
  El modelo principal y su cuantización no cambian.

## Contexto, seguridad y UI

El mensaje actual se conserva completo también en web/móvil. El prefijo estable
precede datos variables. Las observaciones se empaquetan por columnas/filas, sin
eliminar filas ni datos de estilo; se omiten imágenes y resúmenes redundantes.
400–800 tokens es un objetivo, no un resultado medido ni un recorte forzoso.
Scout todavía conoce las firmas del registro; Gemma no vuelve a procesarlas.

ReadToolDefinition clasifica lecturas permitidas. Una nueva ToolDefinition queda
denegada por defecto para ejecución automática. Las mutaciones continúan en
endpoints de dominio e interfaz con autorización y confirmación. Una decisión
del modelo nunca equivale a confirmar una compra o aprobar un pago.

Se mantienen tarjetas, sugerencias y eventos existentes. response_meta añade
agent_mode=scout_tools_gemma_on_demand, model_used y delegated_to_main.
product_picker usa productos reales del chat y selección validada, sin IDs visibles.
Los nuevos store_picker, number_input y cart_diff del diagrama **no se implementan
en esta entrega**. No se sustituyen confirmaciones existentes.

Los endpoints especializados search/outfit/complete/style/value conservan su
recorrido anterior y sus contratos de recomendaciones persistidas. Esta entrega
unifica el **chat REST/WebSocket**, no declara migrado todo el módulo IA.

## Métricas y validación pendiente

AI_CONTEXT registra secciones, caracteres, rol y entidades; cero mensajes históricos.
AI_SCOUT registra ruta, tokens/prefill/caché cuando el servidor los informa y tiempo
total. No se inventa TTFT de Scout, que usa JSON no streaming. Gemma mantiene
AI_INFERENCE. AI_CONTEXT_TOKEN_METRICS=true añade tokenización por sección;
por defecto no introduce esas solicitudes. No se registran textos ni credenciales
en esta telemetría. Datos no observables quedan nulos.

Pendiente por decisión del usuario: elegir/descargar GGUF, activar .env, verificar
compatibilidad y probar conversaciones multitur­no, aislamiento y latencia real.
