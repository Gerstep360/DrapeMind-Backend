# Onboarding, mostrador y vestidor — 2026-09-12

## Implementado

- Web: elección explícita entre sucursales activas, preferencias opcionales sin
  tallas/género/presupuesto preseleccionados, guardado confirmado por servidor y
  consulta opcional de novedades en el chat real. Omitir no guarda un perfil ficticio.
- Diseño web: tokens crema/lima/celeste, controles accesibles, composición adaptable
  y movimiento corto con reduced-motion. Se retiraron mensajes de búsqueda simulados,
  latencias inventadas y respuestas de respaldo atribuidas a Altair.
- Backend: guardar preferencias no genera texto fijo. Si se solicita inferencia,
  utiliza el agente existente. El saludo opcional usa Scout real o informa un error.
- CU-16: después de convertir una reserva, se ofrece cobro explícito en efectivo y
  descarga del comprobante no fiscal en la misma vista.
- CU-24: endpoint formal compatible con recomendación individual y selección completa
  confirmada. La selección reutiliza el servicio batch y sus validaciones; no se
  fabrica un identificador de recomendación persistida.
- CU-37: ya existía pantalla POS en Pedidos. Se añadieron validaciones previas de
  sucursal asignada, precio de catálogo, stock local/global, líneas duplicadas y
  método de pago; los registros de stock se bloquean antes de escribir el pedido.
- CU-39: se reutiliza la máquina de estados, se admite ENCARGADO con alcance de
  sucursal y no se puede marcar PAGADO saltándose el cobro.
- CU-17: corregido el constructor ARConfig incompatible con su esquema público.
  Se devuelve el contrato que Flutter consume, sin tallas ni imagen de respaldo
  inventadas. Flutter admite imágenes SVG/raster, ajuste manual de imagen y un
  estado explícito cuando falta el recurso.

## Límites y verificaciones pendientes

- El vestidor sigue siendo **2D orientativo**, no AR con pose tracking, segmentación
  u oclusión. Sus medidas son estimaciones genéricas, no un escaneo corporal ni física
  textil validada. Hace falta prueba en teléfono y recursos de prendas adecuados.
- La sucursal elegida se conserva mediante BranchService en el navegador; no se añadió
  sincronización de esta preferencia entre dispositivos ni una migración de BD.
- El nuevo onboarding está implementado en Angular. La mejora Flutter de este cambio
  se concentra en el vestidor; no incluye portar toda la encuesta al móvil.
- Verificación visual automática bloqueada: el navegador de pruebas falló al iniciar
  por ACL del entorno. No se afirma inspección visual ni prueba de cámara real.
- No se contactó el VPS, no se cambió `.env`, no se ejecutaron cobros reales ni se
  alteró el archivo de configuración móvil que ya tenía cambios del usuario.

## Comprobaciones locales

- Angular: build de desarrollo.
- Flutter: analyze del vestidor, sin incidencias.
- Backend: regresiones de AR, estados, POS y aplicación de recomendaciones; contratos
  OpenAPI. Son pruebas aisladas, no certifican pagos reales ni concurrencia PostgreSQL.
