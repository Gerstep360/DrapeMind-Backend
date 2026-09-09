# Revisión de casos prioritarios — 9 de septiembre de 2026

No se usan porcentajes de avance: una ruta existente no demuestra un flujo completo.
Trabajo local; sin acceso al VPS. Las capturas de navegador utilizan fixtures, no transacciones reales.

| CU | Evidencia encontrada y cambio | Estado / falta de verificación |
| --- | --- | --- |
| 11 | Iniciar/consultar pago, HMAC, mock restringido, aprobación protegida contra pedido cancelado o ya pagado. | Parcial. No hay adaptador bancario: producción devuelve 503 en vez de generar un QR ficticio. Falta elegir e integrar pasarela, sandbox y conciliación. |
| 14 | Listado, QR y cancelación en web/móvil. QR vencido rechazado. Búsqueda, error/reintento y confirmación accesible en web. | Implementado; UI probada con fixtures. Falta ensayo transaccional completo en PostgreSQL para todos los estados. |
| 15 | Preparar y marcar lista con roles/sucursal. Se rechaza marcar lista una reserva vencida. | Implementado, regresión del vencimiento cubierta. |
| 16 | Validación QR y conversión. La conversión bloquea y recarga la reserva con FOR UPDATE antes de crear pedido. | Implementado con controles reforzados; falta prueba concurrente real de doble conversión. |
| 17 | Cámara, maniquí y superposición manual 2D. Se libera cámara al salir o enviar app al fondo. Sin sustitución por primera talla; error de API ya no inventa configuración local. | Parcial. No hay seguimiento de pose/oclusión real. Falta implementación y prueba en teléfono, assets adecuados y medidas reales de prendas. |
| 20 | Endpoint outfits/generate, herramienta recommend_outfit, chat y tarjetas en ambos clientes. | Existente, conservado. No se afirma calidad universal del modelo; requiere evaluación con catálogo representativo. |
| 21 | Endpoint outfits/complete y contexto de producto base. | Existente, conservado. Falta ensayo completo con distintas prendas base y restricciones. |
| 24 | Aplicación de recomendaciones, lote de carrito y validación de usuario/stock. | Existente, conservado; no se ha ejecutado una compra real como parte de esta revisión. |
| 34 | Existencias por sucursal y asignación de personal. Web añade búsqueda y filtro crítico. | Existente. UI probada con fixtures. Pendiente optimizar carga N+1 y paginar catálogo completo. |
| 35 | Ajustes con motivo, bloqueo, actor y antes/después; historial de movimientos. | Existente. Web explica rechazo si total es menor que reservado y evita guardados simultáneos. |
| 37 | Cobro en efectivo de pedido, pago aprobado y comprobante interno no fiscal. | Parcial. Falta caja de venta directa sin reserva y evaluación de facturación fiscal si se requiere. |
| 38 | Filtros por sucursal/estado, preparación y conversión. | Existente, mejorada la vista de reservas. Falta ensayo con varias cuentas/sucursales reales. |
| 39 | Estados de pedido, entrega y comprobante. Se retira cancelación desde PREPARANDO: no existe flujo de reembolso implementado. | Existente para transición normal; reembolsos y devolución de venta pagada pendientes. |

## Verificación realizada

- Backend: 69 pruebas unitarias/contrato; incluyen pagos sobre pedido cancelado/pagado/entregado, QR/roles existentes y vencimiento de reservas.
- Web: npm run build correcto; advertencia preexistente de presupuesto CSS del chat (31 kB / 30 kB).
- UI: scripts/check-operations-ui.cjs, 1440×960 y 390×844. Búsqueda, filtro crítico, diálogo con Escape, error/reintento y ausencia de overflow del viewport.
- Mobile: flutter analyze sin incidencias; flutter test, 9 pruebas. No equivalen a una prueba física de cámara.
- Las pruebas visuales bloquean tráfico externo y no ejecutan cambios sobre la base de datos.

## Prioridad siguiente

1. Implementar caja directa y validar stock/pago en una transacción con pruebas PostgreSQL.
2. Cubrir conversión/cancelación concurrentes y regresiones de aislamiento por sucursal.
3. Paginar inventario y eliminar múltiples consultas HTTP por producto.
4. Integrar el proveedor de pagos que el propietario elija; nunca guardar credenciales en Git.
5. Implementar tracking corporal y validar CU-17 con hardware real.
