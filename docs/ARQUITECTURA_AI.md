# Arquitectura del Subsistema de Inteligencia Artificial (Backend DrapeMind)

Este documento detalla la arquitectura del subsistema de **Inteligencia Artificial (Altair)** implementado en el backend de DrapeMind Atelier (FastAPI + Gemma 4 local + PostgreSQL).

---

## 1. Diagrama General de Arquitectura (Componentes y Capas)

El sistema opera bajo una arquitectura desacoplada donde el modelo de lenguaje (LLM) no accede directamente a la base de datos, sino que actúa como un motor de razonamiento guiado por herramientas deterministas provistas por FastAPI.

```mermaid
flowchart TB
    subgraph CLIENTES ["Clientes Externos"]
        WEB["Angular Web Client\n(Browser / Desktop)"]
        MOB["Flutter Mobile Client\n(Android / iOS)"]
    end

    subgraph PROXY ["Reverse Proxy Nginx (:80 / :443)"]
        NGINX["Nginx Web Server\n• Proxy Pass /DrapeMind/api/v1/ws/ai\n• Buffering Off (Streaming SSE/WS)\n• Read Timeout 600s"]
    end

    subgraph BACKEND ["FastAPI Backend Enterprise (:8045)"]
        subgraph TRANSPORT ["Capa de Transporte y Autenticación"]
            WS_ENDPOINT["WebSocket Router\n(/api/v1/ws/ai)\n• Handshake JWT (type: auth)\n• Origin Check (CORS)\n• Heartbeat (ping/pong)"]
            REST_ENDPOINT["REST AI Router\n(/api/v1/ai/*)\n• /chat, /search, /outfits\n• /cart/style-check, /value-check"]
        end

        subgraph AGENT_CORE ["Motor del Agente Altair (ReAct Loop)"]
            ORCHESTRATOR["app/services/ai.py\n(Altair Orchestrator)\n• Gestión de Sesión y Memoria\n• Deadline (180s) & Max Steps (4)"]
            REACT_LOOP["app/services/ai_agent.py\n(ReAct Tool Agent Loop)\n• System Prompt DrapeMind\n• Parser JSON (tool vs finish)\n• Inyección de Observaciones Compactas"]
            STREAM_ENGINE["app/services/agent_stream.py\n• Snapshot Emitter\n• Aislamiento de Reasoning\n• Filtro de JSON Interno"]
        end

        subgraph SKILLS_LAYER ["Capa de Habilidades Especializadas (Skills)"]
            SKILL_REG["Skill Registry"]
            SKILL_CAT["Catalog Skill\n(Búsqueda semántica)"]
            SKILL_OUTFIT["Outfit Skill\n(Coordinación de prendas)"]
            SKILL_CART["Cart & Style Skill\n(Chequeo de silueta y ahorro)"]
            SKILL_ORDERS["Orders & Reserve Skill\n(Trazabilidad de compras)"]
        end

        subgraph TOOLS_LAYER ["Capa de Herramientas Parametrizadas (Tools)"]
            TOOLS_CATALOG["app/services/ai_tools.py\n• search_products\n• get_product_detail\n• get_my_cart\n• recommend_outfit\n• analyze_styling\n• get_my_orders\n• get_my_reservations\n• find_alternatives"]
            TOOL_CTX["ToolContext\n(Aislamiento por User ID y Tenant)"]
        end

        subgraph RUNTIME_MGR ["Gestor del Proceso de Inferencia (ModelRuntime)"]
            MODEL_RT["app/services/model_runtime.py\n• Start / Stop de llama-server\n• Idle Timeout (600s)\n• Healthcheck (/health y /v1/models)\n• Subprocess Popen (OpenMP CPU)"]
            SSE_CLIENT["HTTPX Streaming Client\n• POST /v1/chat/completions\n• SSE Parser (data: {choices: ...})\n• First Token Timeout (120s)\n• Reasoning Budget (64 tokens)"]
        end
    end

    subgraph LLM_RUNTIME ["Motor Local de Inferencia llama-server (:8088)"]
        LLAMA_BIN["/usr/local/bin/llama-server\n(llama.cpp release GGML CPU)"]
        subgraph WEIGHTS ["Modelos y Pesos Locales"]
            GEMMA_GGUF["gemma-4-E2B_q4_0-it.gguf\n(Google Gemma 4 E2B QAT Q4_0)"]
            MMPROJ_GGUF["gemma-4-E2B-it-mmproj.gguf\n(Proyector Multimodal)"]
        end
    end

    subgraph PERSISTENCE ["Capa de Persistencia PostgreSQL (:5432)"]
        DB[(PostgreSQL\ndrapemind_db)]
        subgraph DB_TABLES ["Esquema Relacional"]
            T_CAT["Catálogo: Product, Variant, Fabric"]
            T_CART["Carrito y Compras: Cart, CartItem, Order"]
            T_AI["Historial AI: AISession, AIInteraction, AIRecommendation"]
        end
    end

    %% Conexiones
    CLIENTES <-->|WSS / HTTPS| NGINX
    NGINX <-->|Proxy WebSocket / HTTP| TRANSPORT
    WS_ENDPOINT --> ORCHESTRATOR
    REST_ENDPOINT --> ORCHESTRATOR
    ORCHESTRATOR <--> REACT_LOOP
    REACT_LOOP --> STREAM_ENGINE
    STREAM_ENGINE -.->|Eventos WebSocket en tiempo real| WS_ENDPOINT
    REACT_LOOP <--> SKILLS_LAYER
    SKILLS_LAYER <--> TOOLS_LAYER
    TOOLS_LAYER <-->|SQLAlchemy ORM Sessions| DB
    REACT_LOOP <--> RUNTIME_MGR
    RUNTIME_MGR <-->|HTTP SSE Streaming :8088| LLAMA_BIN
    LLAMA_BIN --> WEIGHTS
    DB --- DB_TABLES
```

---

## 2. Diagrama de Secuencia: Flujo de Consulta con Streaming

Este diagrama ilustra la interacción completa desde que el usuario envía un mensaje por WebSocket hasta que recibe la respuesta progresiva:

```mermaid
sequenceDiagram
    autonumber
    actor U as Usuario (Web / Móvil)
    participant WS as WebSocket Endpoint (/ws/ai)
    participant AG as Agente Altair (ai.py & ai_agent.py)
    participant RT as ModelRuntime (model_runtime.py)
    participant LLM as llama-server (:8088 Gemma 4)
    participant TL as Tools & Store (ai_tools.py)
    participant DB as PostgreSQL (drapemind_db)

    U->>WS: JSON { "type": "chat", "message": "¿Qué vestido me recomiendas para gala?", "session_id": "abc" }
    WS->>AG: run_agent_socket(db, user, message, session_id, emit)
    AG->>WS: emit { "type": "start", "session_id": "abc" }
    WS-->>U: Muestra indicador "Pensando..."

    Note over AG,RT: Paso 1: Inicialización o Wake-up del Modelo
    AG->>RT: ensure_running()
    opt Si llama-server está apagado
        RT->>LLM: Inicia subprocess llama-server --model gemma-4-E2B... -c 4096 -t 3
        RT->>LLM: Polling GET /health hasta 200 OK
    end

    Note over AG,LLM: Paso 2: Turno de Razonamiento del Modelo (ReAct)
    AG->>RT: stream_chat(messages, tools_catalog, temperature=0.35)
    RT->>LLM: POST /v1/chat/completions (stream=true, max_tokens=768)
    
    loop Lectura SSE en tiempo real
        LLM-->>RT: SSE chunk: reasoning_content (pensamiento privado)
        RT-->>AG: Token de razonamiento
        AG->>WS: emit { "type": "reasoning", "content": "Analizando código de vestimenta gala..." }
        WS-->>U: Card animada "Pensando: Analizando código de vestimenta gala..."
    end

    LLM-->>RT: Chunk de decisión JSON: {"type": "tool", "name": "search_products", "arguments": {"categoria": "Vestidos", "ocasion": "gala"}}
    
    Note over AG,DB: Paso 3: Ejecución Determinista de Herramienta
    AG->>WS: emit { "type": "tool_call", "tool": "search_products", "label": "Consultando vestidos de gala en catálogo..." }
    WS-->>U: Badge activo: "Consultando vestidos de gala en catálogo..."
    AG->>TL: execute_tool("search_products", kwargs, ToolContext(user))
    TL->>DB: SELECT * FROM products JOIN variants WHERE category='Vestidos'...
    DB-->>TL: 4 productos con stock y precio real
    TL-->>AG: Resultado estructurado (compactado)
    AG->>WS: emit { "type": "tool_result", "tool": "search_products", "status": "success", "count": 4 }

    Note over AG,LLM: Paso 4: Generación de Respuesta Final con Datos Verificados
    AG->>RT: stream_chat(messages + tool_observation)
    RT->>LLM: POST /v1/chat/completions (stream=true)
    
    loop Streaming del texto final
        LLM-->>RT: SSE chunk: answer tokens
        RT-->>AG: Token público
        AG->>WS: emit { "type": "delta", "delta": "Para tu gala te recomiendo el Vestido Zafiro Real..." }
        WS-->>U: Renderizado tipo máquina de escribir del texto
    end

    AG->>DB: Registra AIInteraction & AIRecommendation (sesión persistida)
    AG->>WS: emit { "type": "done", "session_id": "abc", "buttons": [{"label": "Ver en 3D/AR", "prompt": "Quiero probarme el Zafiro"}] }
    WS-->>U: Mensaje final completado con botones de sugerencia interactiva
```

---

## 3. Componentes Clave del Backend de IA

### A. Capa de Transporte WebSocket (`app/api/v1/endpoints/ws.py`)
- **Autenticación en Handshake:** Valida el token JWT antes de permitir la recepción de eventos.
- **Canalización Segura:** Cada conexión se aísla por `user.id`.
- **Serialización Segura:** Utiliza `sanitize_for_json` para transformar recursivamente objetos `Decimal`, `datetime` o referencias circulares en JSON válido.
- **Manejo de Errores e Interrupción:** Atrapa cancelaciones del cliente (`WebSocketDisconnect`) cancelando limpiamente la tarea asíncrona sin dejar procesos zombis.

### B. Orquestador ReAct y Agente Altair (`app/services/ai.py` y `ai_agent.py`)
- **Ciclo ReAct Acotado:**
  - `AI_MAX_AGENT_STEPS = 4` (impide bucles infinitos de llamadas a herramientas).
  - `AI_AGENT_DEADLINE_SECONDS = 180` (límite absoluto para evitar bloqueos en el hilo del usuario).
- **Compactación de Observaciones (`compact_observation`):** Reduce la salida de herramientas como catálogos o carritos a los tokens estrictamente necesarios (nombre, precio, calidad, stock) evitando que el contexto exceda los `4096` tokens del modelo.
- **Separación de Pensamiento Privado:** El campo `reasoning_content` del modelo nunca se mezcla con el texto de salida (`answer`), transmitiéndose al usuario como estados de progreso sutiles.

### C. Gestor de Proceso de Inferencia (`app/services/model_runtime.py`)
- **Inferencia CPU Local:** Llama nativamente al binario precompilado `/usr/local/bin/llama-server` compilado con librerías `libggml-cpu-x64.so` y soporte OpenMP.
- **Gestión On-Demand (Bajo Demanda):** El proceso de IA se activa únicamente cuando un usuario interactúa.
- **Auto-Unload por Inactividad:** Si transcurren `AI_IDLE_TIMEOUT_SECONDS = 600` (10 minutos) sin consultas, el servidor libera automáticamente la memoria RAM del VPS.
- **Resiliencia de Timeout:**
  - `AI_FIRST_TOKEN_TIMEOUT_SECONDS = 120`: Tolerancia adecuada para el primer token en arquitecturas CPU x86_64.
  - `AI_TIMEOUT_SECONDS = 90`: Timeout por token subsiguiente.

### D. Catálogo de Herramientas Autorizadas (`app/services/ai_tools.py`)
El modelo **no tiene acceso a comandos del sistema ni a SQL directo**. Solo puede solicitar la ejecución de herramientas pre-aprobadas:
1. `search_products`: Búsqueda filtrada con control de stock y tallas.
2. `get_product_detail`: Especificaciones de tela, color, medidas y fotos 3D/AR.
3. `get_my_cart`: Inspección del carrito del usuario activo.
4. `recommend_outfit`: Combinación armónica de hasta 4 piezas dentro de un presupuesto exacto.
5. `analyze_styling`: Validación de siluetas, ocasión y paleta de color.
6. `get_my_orders` y `get_my_reservations`: Consulta del estado logístico del usuario.
7. `find_alternatives`: Búsqueda de piezas de menor costo o diferente color manteniendo la armonía.

---

## 4. Matriz de Parámetros de Inferencia en Producción

| Parámetro | Valor Producción | Propósito |
| :--- | :--- | :--- |
| **`AI_MODEL`** | `google/gemma-4-E2B-it-qat-q4_0-gguf` | Modelo cuantizado Q4_0 optimizado para inferencia rápida en CPU. |
| **`AI_CONTEXT_SIZE`** | `4096` tokens | Ventana total de contexto para historial, catálogo y respuesta. |
| **`AI_MAX_TOKENS`** | `1024` tokens | Límite máximo de salida por turno. |
| **`AI_AGENT_MAX_TOKENS`** | `768` tokens | Límite de generación por paso de agente. |
| **`AI_THREADS`** | `3` (o núcleos CPU - 1) | Balance entre velocidad de cálculo y carga general del VPS. |
| **`AI_TEMPERATURE`** | `0.35` | Respuestas enfocadas, precisas y sin alucinaciones de inventario. |
| **`AI_FIRST_TOKEN_TIMEOUT`** | `120s` | Ventana de arranque para el primer token en servidores virtuales. |
| **`AI_IDLE_TIMEOUT`** | `600s` | Descarga de memoria tras 10 minutos sin actividad. |
| **`AI_REASONING_BUDGET`** | `64` tokens | Límite de tokens dedicados al razonamiento previo a la respuesta. |

---

> [!NOTE]
> Toda la inferencia es **100% privada y local** dentro del servidor VPS (`127.0.0.1:8088`). Ningún dato de clientes, carritos o compras es enviado a APIs externas de terceros.
