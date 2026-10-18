# Compras personales y formularios del chat

El chat usa el mensaje explícito como primera prioridad, los criterios de la conversación después y el perfil guardado como base. El perfil se carga con tallas, colores, estilos, ocasiones, presupuesto y ciudad de la dirección principal, sin transmitir dirección exacta ni teléfono al modelo. Las búsquedas no modifican el perfil.

## Herramientas de lectura

| Herramienta | Datos y comportamiento |
| --- | --- |
| `get_my_shopping_context` | Perfil de compras y categorías reales para orientar la consulta. |
| `discover_for_me` | Variantes con stock y talla exacta. Filtros explícitos sobre preferencias; colores y estilos guardados ordenan las coincidencias. No devuelve un catálogo ajeno a la consulta si no encuentra resultados. |
| `recommend_pickup_branches` | Cantidades del carrito o variantes indicadas; ordena por selección completa, ciudad y cobertura. No estima distancias ni viajes. |
| `plan_more_for_less` | Precios menores entre coincidencias disponibles, una unidad por prenda, máximo seis, dentro del presupuesto. El saldo no se presenta como descuento. |
| `find_cart_savings` | Sustituciones de la misma categoría y talla, mismo color por defecto y cantidades conservadas. Calcula con Decimal la diferencia de precios y extras que caben en el ahorro. No modifica el carrito. |
| `ask_shopping_preferences` | El modelo selecciona objetivo y campos faltantes de una lista fija. El servidor genera el formulario, termina el turno y espera confirmación. |

Las novedades requieren una fecha de ingreso real dentro del intervalo consultado. Las coincidencias recientes se señalan durante la exploración personal sin otra llamada al modelo. No se garantiza ajuste físico: el catálogo no dispone de medidas de prenda y la antigua herramienta dejó de inventar centímetros de pecho u holgura.

## Formularios y uso de IA

Abrir una herramienta usa `GET /api/v1/ai/shopping-setup?goal=...&session_id=...`, autenticado y con verificación de propiedad de la sesión. La respuesta contiene un componente `shopping_question` con valores guardados precargados. Esta operación solo lee PostgreSQL; **no llama a NVIDIA**.

El cliente puede revisar o editar los criterios. No se envía un mensaje al escribir en los campos. «Buscar con estos datos» emite una solicitud con el objetivo, petición original y valores confirmados. El formulario valida importes y opciones y evita enviar dos veces la misma confirmación. Los mensajes libres también pueden producir un formulario cuando el modelo detecta información necesaria que falta; no se mantienen llamadas al proveedor ni tareas esperando la entrada del cliente.

Los componentes `shopping_summary` y `branch_options` muestran criterios, razones, importes, diferencias y cobertura. Todo el contenido comercial procede de herramientas autorizadas. No se ejecutan HTML, CSS, SQL ni acciones arbitrarias del modelo. El servidor conserva criterios explícitos en el contexto de la conversación y mezcla únicamente los cambios del turno con las conversaciones concurrentes.

## Validación de esta entrega

- Backend: 118 pruebas correctas, incluyendo prioridad de criterios, tallas exactas, calzado, Decimal, cantidades, stock por sucursal, novedades por fecha, formularios, pausa y persistencia de criterios.
- Web: 19 pruebas correctas y `npm run build:prod` correcto. Los formularios no emiten mensajes antes de confirmar, validan el presupuesto y conservan el borrador al cambiar la capacidad del chat.
- `python -m scripts.diagnostics.check_personal_shopping`: NVIDIA real verificó perfil, talla explícita, presupuesto y precios de PostgreSQL, ahorro sin cambiar el carrito, formulario de ciudad y consulta retomada. Usa y elimina una cuenta QA; conserva catálogo y perfiles reales.
- No había navegador conectado a Computer Use; no se acreditan capturas ni revisión visual de estos componentes en esta sesión.

Las consultas de recomendaciones evalúan hasta 2000 variantes después de filtrar. Si alcanzan el límite, el componente lo indica; no promete un óptimo global. No se aplican cupones supuestos ni se incluyen gastos de envío desconocidos en los planes.

En la base local, la comprobación encontró cero ingresos en los últimos 30 días. La ausencia de novedades produce un resultado vacío; no se sustituye por prendas antiguas etiquetadas como nuevas. La prueba de exploración general consulta prendas disponibles y no exige novedades inexistentes.
