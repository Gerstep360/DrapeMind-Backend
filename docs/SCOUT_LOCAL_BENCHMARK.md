# Scout: medición local y cancelación

Pruebas aisladas con Qwen3-0.6B-Q8_0, CPU, un hilo y caché de prefijo. No se accedió al VPS, no se cambió Gemma y no se ejecutaron herramientas contra cuentas reales. Los tiempos no predicen el rendimiento de la CPU compartida del VPS.

| Prueba | Antes | Después | Alcance |
| --- | ---: | ---: | --- |
| Saludo `Buen día`, caliente | 2,06 s | 1,75 s | Decisión y respuesta de Scout |
| Consulta de artículos de la cesta | 2,56 s, promesa sin consulta | 1,66 s, `get_my_cart` | Selección de herramienta, no ejecución de carrito |
| `hola`, frío, antes/después de optimizar readiness | 17,01 s | 9,26 s | Incluye carga y preparación |
| `hola`, caliente, después de readiness | — | 1,19 s | 912 de 913 tokens reutilizados |

El prompt inicial pasó de 1120 a aproximadamente 914 tokens. El último prefill frío de `hola` fue 6091 ms; generación, 1282 ms. El resto incluye arranque y transporte. Son muestras individuales, no percentiles ni una prueba de carga.

## Cambios

- Contrato de transporte `action` derivado del registro real de tools, traducido al contrato interno existente. Se conservan contexto, UI, planes y presupuesto de respuesta.
- Instrucciones breves en español y mensaje actual íntegro separado de las instrucciones.
- Tools estáticas antes del contexto variable; métricas adaptadas al nuevo formato.
- Readiness local con conexión corta y sin repetir `/models` tras un fallo TCP.
- Cola de inferencia limitada a cinco segundos, separada del límite de generación.
- Desconexión cancela la tarea; restauración del navegador no revive indicadores pendientes.

## Verificación

`python -m unittest discover -s tests -p test_scout_lifecycle.py -v`: cuatro pruebas correctas (cancelación, liberación de cola, límite de espera, mensaje íntegro).

Angular: `npm run build -- --configuration development`, compilación correcta. La composición inicial y legibilidad se ajustaron; no se realizó inspección visual en navegador.

Benchmark reproducible: desde backend, `PYTHONPATH=.` y `python scripts/benchmark_scout_local.py`; también admite mensajes como argumentos. Requiere Scout local configurado y termina únicamente el proceso administrado que inició. No descarga modelos ni modifica datos.

## Límites pendientes

No se validó todavía una conversación completa con base de datos, UI y resultados del carrito real. Tres tipos de entrada no acreditan inteligencia general: el modelo pequeño aún puede redactar mal o seleccionar incorrectamente en otros casos. No se garantiza respuesta instantánea en frío ni precisión universal. No se desplegó al VPS.
