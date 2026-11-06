# Herramientas nativas y MCP

Altair usa llamadas de función nativas de NVIDIA. El modelo recibe los esquemas del registro `app/services/ai_tools.py`, elige herramientas y recibe sus resultados antes de decidir la siguiente llamada. No hay skills cargadas desde archivos ni un clasificador de frases que seleccione recorridos. Los componentes de presentación no finalizan una lectura automáticamente.

El registro contiene 25 consultas para clientes y 30 para administradores. Incluye catálogo, novedades, preferencias, carrito, ahorro, presupuestos, sucursales, disponibilidad, pedidos, reservas, pagos, políticas y medidas registradas; el administrador también puede consultar indicadores, demanda, reportes guardados, proveedores y abastecimiento. Las operaciones que modifican datos conservan las acciones confirmadas de la interfaz.

Agregar una capacidad implica registrar nombre, descripción, modelo de argumentos, función y permisos. El registro alimenta tanto `tools` de NVIDIA como `tools/list` de MCP. No se añade una rama al prompt ni al agente. La presentación reutiliza componentes prefabricados y resultados del servidor; nombres, precios y existencias no se aceptan del texto generado.

## MCP HTTP

Endpoint local: `http://127.0.0.1:8000/api/v1/mcp`.
Endpoint VPS: `https://167.86.106.105/DrapeMind/api/v1/mcp`.

Transporte Streamable HTTP con respuestas JSON, compatible con MCP 2025-11-25 y 2025-06-18. Implementa `initialize`, `notifications/initialized`, `ping`, `tools/list` y `tools/call`. No anuncia suscripciones SSE ni sesiones; GET devuelve 405. Requiere el JWT de una sesión empresarial de DrapeMind. No incluye descubrimiento OAuth para conectar cuentas externas automáticamente.

Cabeceras del cliente:

```http
Authorization: Bearer <JWT de DrapeMind>
Content-Type: application/json
Accept: application/json, text/event-stream
MCP-Protocol-Version: 2025-11-25
```

```json
{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-11-25","capabilities":{},"clientInfo":{"name":"cliente","version":"1"}}}
```

```json
{"jsonrpc":"2.0","id":2,"method":"tools/list"}
```

```json
{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"get_catalog_overview","arguments":{}}}
```

La empresa se obtiene del JWT y no de los argumentos. Se valida Origin cuando existe. Las llamadas pasan por el mismo ejecutor y aislamiento PostgreSQL que Altair. Un cliente no descubre ni ejecuta herramientas empresariales reservadas al administrador.

## Comportamiento y coste

Consultar el carrito devuelve solo su contenido. Si el usuario pide novedades cuando esté vacío, el modelo puede consultar el carrito y después las novedades en el mismo turno. Novedades generales no oculta filtros de talla o presupuesto: `use_profile` es explícito. `get_catalog_overview` diferencia falta de novedades, falta de stock y tienda vacía.

Las instrucciones de sistema pasan de 4.373 a 1.953 caracteres. Esta medida no equivale a un número exacto de tokens. Los esquemas y resultados siguen consumiendo contexto; MCP no elimina ese coste. El chat usa el registro directamente, sin una petición HTTP interna adicional. Los límites de llamadas y tiempo siguen siendo configurables.

Referencias: [transporte MCP](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports), [herramientas MCP](https://modelcontextprotocol.io/specification/2025-11-25/server/tools), [NVIDIA Bolt](https://docs.api.nvidia.com/nim/reference/nvidia-nemotron-3_5-bolt-e4b-infer).
