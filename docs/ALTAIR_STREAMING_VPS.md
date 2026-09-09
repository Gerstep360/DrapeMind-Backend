# Altair: streaming y perfil CPU

## Correcciones implementadas

- La ruta del agente solicita streaming real a llama-server y entrega snapshots del campo público answer por WebSocket. Web y Flutter muestran ese texto mientras se genera.
- No se retransmiten razonamiento privado, reasoning_content ni JSON de llamadas como respuesta del asistente.
- Esperar/cargar no cuenta como una consulta verificada. Acciones contiene herramientas ejecutadas; los errores no llevan estado de éxito.
- El modelo recibe el catálogo actual de herramientas en cada turno y puede generar hasta tres botones label/prompt. Los botones envían una nueva consulta; no ejecutan código arbitrario.
- Se eliminó el límite fijo de 1024 tokens del bucle: usa AI_AGENT_MAX_TOKENS. Se compactan esquemas y observaciones sin cortar JSON por caracteres.
- Fallos de inferencia y agotamiento de pasos sin respuesta válida se notifican como errores, no como una respuesta genérica exitosa.
- Se eliminó la animación de escritura artificial por bloques después de completar la inferencia.

## Perfil inicial para 4 vCPU / 8 GB RAM, sin GPU

Copiar solamente estos ajustes al entorno del servidor, conservando sus secretos y rutas. La plantilla .env.production.example está actualizada; no reemplazar todo el .env de producción.

```dotenv
AI_CONTEXT_SIZE=4096
AI_PARALLEL_SLOTS=1
AI_THREADS=3
AI_GPU_LAYERS=0
AI_AGENT_MAX_TOKENS=768
AI_AGENT_DEADLINE_SECONDS=180
AI_TIMEOUT_SECONDS=90
AI_MAX_AGENT_STEPS=4
AI_REASONING_MODE=auto
AI_IDLE_TIMEOUT_SECONDS=600
```

AI_AGENT_DEADLINE_SECONDS limita cada decisión del modelo, no la conversación completa. AI_TIMEOUT_SECONDS limita inactividad HTTP; el streaming evita esperar toda la respuesta antes de recibir datos. Cuatro decisiones pueden tardar bastante más que una. Auto permite el comportamiento de razonamiento que soporte la plantilla del modelo; no garantiza calidad ni rapidez.

Reiniciar backend y su proceso administrado de inferencia para aplicar opciones de arranque. Un llama-server iniciado externamente debe reiniciarse con sus opciones equivalentes. No hace falta Docker. No exponer el puerto de inferencia a Internet.

## Qué significa agente real

Gemma selecciona herramientas y argumentos, observa resultados y redacta la respuesta. FastAPI conserva validación de usuario, permisos, stock y cálculos. No existe garantía de que un modelo pequeño interprete correctamente toda consulta. El registro informa capacidades presentes, no un historial de versiones; por sí solo no permite afirmar qué se agregó ayer.

Las etiquetas de espera son estados de interfaz, no pensamientos inventados. El motivo público de una llamada procede del campo reason generado por Gemma. El botón sugerido tampoco amplía permisos.

## Verificación y límites

Pruebas del backend incluyen deltas SSE, JSON anidado, registro dinámico, sugerencias del modelo y propagación de errores. Usan transporte/modelo simulado para probar el protocolo, no demostrar calidad semántica de Gemma.

El modelo local no respondió a /health durante esta revisión. No se midieron latencia ni RAM del VPS, ni se verificó una conversación real contra PostgreSQL. PostgreSQL permaneció apagado.

El perfil es un punto de partida, no una promesa de respuesta instantánea. Medir primer texto visible, tiempo total, memoria residente y calidad en preguntas nuevas antes de producción. Las conversaciones largas aún pueden agotar contexto: si ocurre, revisar logs y dimensionar memoria/contexto; no aumentar tokens sin medir.

Pendiente: inspección visual en navegador/dispositivo y prueba de extremo a extremo con los servicios disponibles. El cambio de UI conserva los colores del atelier, limita el ancho de lectura y respeta movimiento reducido en los indicadores modificados.
