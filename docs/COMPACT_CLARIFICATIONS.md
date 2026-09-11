# Aclaraciones compactas después de herramientas

Cuando una herramienta devuelve `status=needs_input`, no se vuelve a enviar el catálogo de herramientas a Scout. El backend obtiene las descripciones de `missing_fields` del schema de esa herramienta y entrega a Gemma el mensaje íntegro, el estado del chat y esos campos. No se modifica el modelo, la cuantización, el razonamiento ni el presupuesto de salida.

La variante que usaba Scout para redactar la pregunta fue descartada: fue rápida pero produjo preguntas incorrectas en pruebas reales. La ruta final evita esa inferencia adicional de planificación y usa un prompt específico de aclaración con Gemma.

## Medición local

Gemma configurado temporalmente para la prueba con 3 hilos, contexto 4096 y razonamiento 64. Puerto local aislado. Las observaciones son sintéticas; no se ejecutaron consultas de inventario ni carrito reales.

| Caso | Entrada | Salida, incluido razonamiento | Tiempo |
| --- | ---: | ---: | ---: |
| Camisa M, presupuesto 650 Bs; faltan talla inferior y ocasión | 228 tokens | 88 tokens | 16,30 s, incluido arranque |
| Camisa M, presupuesto condicional; mismos datos faltantes | 240 tokens | 89 tokens | 8,02 s, modelo cargado |

En ambos casos la pregunta final solicitó talla del pantalón/falda y ocasión/estilo, sin repetir la talla superior conocida. Esto valida esas aclaraciones, no la interpretación completa del presupuesto condicional ni la recomendación final de un outfit. No comparar estos tiempos aislados con los 87 segundos de un turno completo del VPS.

## Despliegue

`SCOUT_COMPACT_CLARIFICATIONS=true` está en `.env.example` y en los valores gestionados de `scripts/migrate_ai_env.py`. `install.sh` ya invoca `sync_env_production`, que llama a ese migrador. Una instalación existente recibe la clave ausente. Un valor personalizado `false` se conserva; también se preservan hilos personalizados y secretos. No se ejecutó el instalador contra producción.

## Regresiones corregidas y verificadas

- La ruta de Gemma sin streaming inicializa su reloj: el logger ya no lanza `UnboundLocalError` después de generar una respuesta.
- Los probes de `localhost` conservan tiempo para resolver nombre y fallback IPv6/IPv4; el plazo corto queda solo para IPs loopback literales.
- El cliente de inferencia no hereda proxies del entorno.
- Nueve pruebas locales correctas: ciclo de vida, filtros, duplicados, aclaración compacta, retorno sin streaming y migración en archivos temporales.

Reproducción: `PYTHONPATH=.` y `python scripts/benchmark_scout_clarification.py` desde backend, con endpoints locales y los parámetros de prueba configurados mediante variables de entorno. El script no descarga modelos ni modifica la base de datos; libera los procesos de modelo administrados que inició.
