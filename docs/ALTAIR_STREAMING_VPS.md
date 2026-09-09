# Altair: streaming y perfil CPU

## Diagnóstico con estadísticas del VPS proporcionadas por el usuario

Los logs muestran 1981 tokens de entrada procesados en 78,45 s (25,25 tokens/s).
La siguiente llamada agrega 857 tokens y tarda otros 35,68 s en procesarlos.
La generación ronda 7–8 tokens/s. El modelo carga en aproximadamente 6,5 s.
Por tanto, en esas consultas domina el procesamiento de contexto y repetir una inferencia,
no solamente la longitud del texto visible. Estos datos no demuestran swap ni CPU steal.

Cambios de esta revisión:

- Índice compacto de firmas de herramientas, conservando nombres de argumentos y tipos;
  validación completa en Pydantic, como antes.
- Respuesta Markdown libre y JSON para solicitar herramientas. Los nombres y argumentos se
  validan contra el registro, sin forzar toda la redacción a una gramática JSON.
- El modelo puede elegir display=cards para un listado y concluir tras recibir tarjetas reales,
  sin una segunda generación. Si el resultado está vacío continúa para explicarlo.
- Evento results: web y móvil muestran las tarjetas antes de la explicación final.
- Instrucciones distinguen capacidades generales, funciones integradas y novedades del catálogo.
  No se agregaron reglas por palabras del usuario ni respuestas especiales a sus preguntas.
- Se elimina la asignación incorrecta de un directorio a GGML_BACKEND_PATH.
  Los logs mostraban que ese aviso no impedía cargar el modelo.

Las pruebas con transporte simulado verifican el protocolo, no inteligencia. El benchmark local
usa preguntas independientes, base de datos READ ONLY y comprueba sintaxis de la muestra de Python
sin ejecutar código generado. No garantiza corrección de todas las respuestas.

No se contactó el VPS. Para medir la mejora allí es necesario comparar nuevos logs después de
actualizar. Reducir contexto y llamadas ayuda, pero no convierte un VPS CPU en un servidor GPU.

## Revisión posterior: timeout real y mediciones locales

El debug recibido muestra TimeoutError al agotarse el límite absoluto de 180 s durante la lectura SSE.
Eso confirma el punto de fallo, no permite medir la velocidad del VPS ni demostrar por sí solo la causa interna del modelo.

Se añadió AI_REASONING_BUDGET=64 (CLI y petición), AI_FIRST_TOKEN_TIMEOUT_SECONDS=120 (en VPS de 4 vCPUs sin GPU el prefill del catálogo requiere hasta 60-90s antes del primer delta) y un error público legible.
La lectura termina cuando llega una decisión JSON completa; no espera espacios o generación posterior al objeto.
El catálogo estable precede al mensaje variable para reutilizar el prefijo cacheado.
Los logs contienen tiempo hasta primer delta, duración, caracteres públicos/de razonamiento y motivo de finalización, sin volcar pensamientos.

Mediciones con el GGUF local real, CPU, 3 hilos y contexto 4096:

| Consulta independiente | Tiempo total | Primer contenido del protocolo |
| --- | ---: | ---: |
| Explicar capacidades | 23,09 s | 13,83 s |
| Orientación sobre tejido | 12,11 s | 6,52 s |
| Búsqueda mediante search_products + PostgreSQL local | 31,94 s | No medido por separado |

El primer contenido del protocolo puede preceder al texto público visible: incluye el comienzo del JSON.
La consulta de catálogo se ejecutó en una transacción READ ONLY y se cerró con rollback.
El benchmark reproducible es scripts/benchmark_agent_local.py --database; siempre fuerza loopback y solo termina el proceso que él creó.
No se contactó el VPS. Estos tiempos no son una garantía de rendimiento en ese servidor.

Validación actualizada: 60 pruebas backend aprobadas. La nota histórica de falta de modelo al final de este documento corresponde a la revisión anterior y queda superada por estas mediciones locales.

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
AI_FIRST_TOKEN_TIMEOUT_SECONDS=120
AI_MAX_AGENT_STEPS=4
AI_REASONING_MODE=auto
AI_REASONING_BUDGET=64
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
