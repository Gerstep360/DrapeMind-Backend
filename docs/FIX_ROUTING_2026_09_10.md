# Incidente VPS: Scout desactivado y respuesta agotada

El traceback adjunto entra desde ai.py directamente al agente legacy. El sincronizador
01_env.sh sobrescribía SCOUT_ENABLED=false y los límites de IA en cada actualización.
Ahora las claves de IA se añaden solo si faltan; las existentes permanecen.

El log muestra 2134 tokens nuevos procesados durante unos 88 segundos y más de
650 tokens generados antes del timeout. No demuestra que Scout atendiera ese turno.
La representación tabular conservaba campos que sí se omitían en objetos individuales;
ahora omite imágenes, costo interno y resúmenes redundantes en ambos formatos.

Filtros de corte/tipo sin coincidencias ahora devuelven grupos vacíos, no sustitutos.
La herramienta de outfit requiere ocasión y tallas superior/inferior para seleccionar
variantes; si faltan solicita información. Esto no garantiza comprensión perfecta
del modelo: requiere validación multitur­no pendiente.

La ruta legacy tiene AI_TURN_TIMEOUT_SECONDS=150 como límite total, incluyendo
espera y carga. La ruta Scout conserva su límite propio. La web elimina tarjetas
provisionales cuando el turno falla, conservando el registro de acciones.

## Después de actualizar

1. Si el GGUF pequeño está instalado, revisar SCOUT_MODEL, SCOUT_MODEL_PATH y puerto.
2. Corregir SCOUT_ENABLED=true en el .env activo; sincronizar ya no revierte ese valor.
3. Reiniciar el backend. AI_ROUTING debe indicar scout, no legacy_gemma.
4. /health/ai informa routing_mode y scout_configured; este último no prueba que
   el archivo exista o que la inferencia funcione, solo indica configuración básica.

Sin modelo pequeño instalado no se debe activar Scout. No se descargó ni activó
ningún modelo, no se contactó al VPS y no se ejecutaron pruebas o inferencias.
