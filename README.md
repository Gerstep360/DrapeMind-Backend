# DrapeMind Backend

FastAPI, PostgreSQL, JWT, WebSockets y Gemma GGUF para la tienda de ropa. No usa Docker.

## Arquitectura segura

```text
Angular / Flutter
       |
       v
FastAPI (JWT, roles, CORS, stock, precios y transacciones)
   |                     |
   v                     v
PostgreSQL          llama-server administrado
                          |
                          v
 google/gemma-4-E2B-it-qat-q4_0-gguf
```

Gemma nunca recibe credenciales ni acceso SQL. El agente solo puede invocar herramientas con
schemas controlados por FastAPI: busqueda de catalogo, carrito, stock, alternativas, pedidos,
reservas y calculos deterministas. Los totales, comparaciones de precio/calidad, permisos y
mutaciones se resuelven en Python/PostgreSQL.

## Requisitos

- Python 3.12 recomendado.
- PostgreSQL 15 o superior.
- `llama-server` de llama.cpp.
- Los dos GGUF en `ai_models/gemma-4-e2b/`.
- [requirements.txt](requirements.txt) fija las dependencias de API, PostgreSQL, JWT, QR y pruebas.

## Windows local

Desde `backend/`:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
Copy-Item .env.example .env
```

Genera secretos reales para `SECRET_KEY` y `PAYMENT_WEBHOOK_SECRET`. Luego crea la base vacia y
aplica el esquema una sola vez:

```powershell
createdb -U postgres drapemind_db
psql -U postgres -d drapemind_db -f database/schema.sql
.\scripts\start_backend.ps1
```

En Windows se autodetecta `vendor/llama.cpp/llama-server.exe` si existe. Vulkan no forma parte de
la arquitectura ni es requisito del VPS: es solamente una aceleracion local opcional.

## Linux / VPS

Compila o instala llama.cpp y deja el ejecutable accesible, por ejemplo:

```dotenv
ENVIRONMENT=production
LLAMA_SERVER_PATH=/opt/llama.cpp/build/bin/llama-server
AI_GPU_LAYERS=auto
AI_IDLE_TIMEOUT_SECONDS=600
```

Con CPU usa `AI_GPU_LAYERS=0`; con CUDA/ROCm usa el build correspondiente de llama.cpp. FastAPI
inicia Gemma con la primera consulta, conserva el proceso mientras haya peticiones activas y lo
apaga despues del periodo de inactividad. La siguiente consulta vuelve a iniciarlo.

El servicio de referencia esta en [drapemind-api.service](deploy/systemd/drapemind-api.service).
Usa un proceso Uvicorn porque el runtime y el bus de eventos son locales al proceso. Para escalar
horizontalmente, ejecuta llama-server como servicio independiente y reemplaza el bus por Redis.

## Ejecucion y URLs

```powershell
.\scripts\start_backend.ps1
```

```bash
./scripts/start_backend.sh
```

- Swagger: <http://localhost:8000/docs>
- ReDoc: <http://localhost:8000/redoc>
- OpenAPI: <http://localhost:8000/api/v1/openapi.json>
- PostgreSQL: <http://localhost:8000/health/ready>
- Gemma/runtime: <http://localhost:8000/health/ai>

Antes de iniciar una base existente, aplica la migración y actualiza los datos operativos:

```powershell
.\.venv\Scripts\alembic.exe upgrade head
.\.venv\Scripts\python.exe scripts\seed_data.py
```

## CORS y WebSockets

`CORS_ORIGINS` es JSON estricto:

```dotenv
CORS_ORIGINS='["http://localhost:4200","https://tienda.midominio.com"]'
```

El frontend no puede habilitar CORS: debe autorizarse aqui. En produccion se recomienda servir
Angular y hacer proxy de `/api` en el mismo dominio; asi REST y WebSocket son same-origin. El
handshake WebSocket valida `Origin` y el primer frame debe autenticar el JWT.

Canales:

- `/api/v1/ws/ai`: tokens de Gemma, pasos de tools, estado de carga y errores.
- `/api/v1/ws/events`: cambios importantes de pedidos, pagos, reservas e inventario.

El canal de IA decide el formato por consulta: `text`, `cards` o `mixed`. Emite
`tool_start`, `tool_result`, `presentation`, cero o más `token` y finalmente `done`.
`done` incluye `action_items`, `response_title` y `duration_ms`; el frontend conserva ese
rastro dentro de cada respuesta.

Gemma trabaja en un ciclo acotado **observar → actuar → observar → responder**. El modelo interpreta
la consulta completa y elige por su cuenta la tool y sus argumentos. FastAPI no clasifica la intención:
valida permisos, argumentos Pydantic, stock, precios, cálculos y transacciones antes de ejecutar cada
acción. El catálogo de tools se compacta para reducir tokens y el máximo de pasos evita bucles.

Para comprobar el protocolo con inferencia y catálogo reales:

```powershell
python -m scripts.check_agent_protocol
```

Las tallas y medidas siguen siendo restricciones duras de las tools. `PUT /api/v1/cart/items/batch`
valida toda la selección y luego reemplaza el carrito en una sola transacción; si falla una prenda,
conserva el carrito anterior.

## Usuarios internos

`POST /auth/register` solo crea CLIENTE. Crea roles internos desde consola:

```powershell
python scripts/create_user.py --email admin@drapemind.local --name Administrador --role ADMIN
python scripts/create_user.py --email ventas@drapemind.local --name Vendedor --role VENDEDOR
```

## Calidad

```powershell
python -m pytest
python -m ruff check app tests
```

Consulta [CU01_20_BACKEND.md](docs/CU01_20_BACKEND.md) para la trazabilidad vigente de los primeros
20 casos de uso y [ENDPOINTS.md](docs/ENDPOINTS.md) para el inventario extendido.
