# Optimización de planes Scout

Implementado sin ejecutar pruebas, inferencias ni benchmarks. No se contactó al VPS.
Los logs recibidos muestran 54 s de generación frente a 5,8 s de prefill en un caso,
pero no permiten atribuir todas las llamadas a una conversación.

## Cambios

- Scout puede emitir calls=[{tool,arguments}] para hasta cuatro consultas conocidas.
- after=cards finaliza con tarjetas e intro neutra, sin otra inferencia, si hay
  resultados válidos y confianza suficiente; after=delegate llama a Gemma directamente.
- after=observe conserva la planificación adicional para dependencias o datos faltantes.
- Gemma: cero o una llamada por turno Scout; short/normal/deep disponen de
  128/256/512 tokens de respuesta, más el razonamiento original intacto.
- Una salida cortada se conserva señalada como parcial; no inicia reintentos ocultos.
- Confianza baja escala a Gemma. La confianza autodeclarada no es precisión medida.
- Nueva capacidad: esquema Pydantic, handler y ReadToolDefinition; card_renderer
  opcional devuelve tarjetas de servidor sin modificar ramas del router.
- El registro y su orden siguen estables. No hay clasificación por palabras clave.
- El botón de una prenda ya en carrito abre sus opciones en vez de volver a agregarla.

## Configuración y observabilidad

Actualizar manualmente .env si ya tenía valores anteriores: SCOUT_THREADS=1,
SCOUT_MAX_TOKENS=256, SCOUT_DIRECT_CONFIDENCE=0.85. Las variables
AI_RESPONSE_SHORT_TOKENS=128, AI_RESPONSE_NORMAL_TOKENS=256 y
AI_RESPONSE_DEEP_TOKENS=512 permiten ajustar la salida sin alterar el razonamiento.
No se activó Scout automáticamente ni se modificó el entorno de producción.

AI_ROUTING informa scout o legacy_gemma al arrancar. AI_TURN registra scout_calls,
gemma_calls, tools, response_budget y tiempo total por chat, sin contenido privado.
La reducción de latencia queda pendiente de medición del usuario.

Los lotes son secuenciales: no se comparte una sesión SQLAlchemy entre hilos.
REST chat y WebSocket comparten circuito. Los endpoints especializados antiguos
aún mantienen sus contratos y recorrido previo. No se declara migrado todo el módulo.
