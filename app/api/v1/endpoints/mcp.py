"""MCP 2025-11-25 tools over stateless Streamable HTTP (JSON responses).

Uses DrapeMind bearer JWTs. OAuth discovery, SSE subscriptions and writes are
intentionally not advertised. The native NVIDIA agent uses this same registry
in-process, without a second HTTP hop or a duplicated tool implementation.
"""

import json
import re
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
from sqlalchemy.orm import Session
from app.api.deps import get_current_user
from app.core.config import settings
from app.db.session import get_db
from app.models import User
from app.services.ai_tools import TOOLS, ToolContext, execute_tool, tool_catalog

router = APIRouter(tags=["MCP"])
VERSION = "2025-11-25"
SUPPORTED = {VERSION, "2025-06-18"}


def error(identity, code, message, status=200):
    return JSONResponse(
        {"jsonrpc": "2.0", "id": identity, "error": {"code": code, "message": message}},
        status_code=status,
    )


def validate_origin(request):
    origin = request.headers.get("origin")
    if origin:
        allowed = origin in settings.CORS_ORIGINS or bool(
            settings.CORS_ORIGIN_REGEX
            and re.fullmatch(settings.CORS_ORIGIN_REGEX, origin)
        )
        if not allowed:
            raise HTTPException(403, "Origen MCP no permitido")


@router.get("/mcp")
def no_subscription(request: Request, user: User = Depends(get_current_user)):
    validate_origin(request)
    return Response(status_code=405, headers={"Allow": "POST"})


@router.post("/mcp")
async def mcp(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    validate_origin(request)
    accept = request.headers.get("accept", "")
    if "application/json" not in accept or "text/event-stream" not in accept:
        return error(
            None,
            -32600,
            "Accept debe incluir application/json y text/event-stream",
            406,
        )
    if request.headers.get("content-type", "").split(";")[0] != "application/json":
        return error(None, -32600, "Content-Type debe ser application/json", 415)
    raw = await request.body()
    if len(raw) > 65536:
        return error(None, -32600, "Solicitud demasiado grande", 413)
    try:
        body = json.loads(raw)
    except ValueError:
        return error(None, -32700, "JSON inválido", 400)
    if (
        not isinstance(body, dict)
        or body.get("jsonrpc") != "2.0"
        or not isinstance(body.get("method"), str)
    ):
        return error(None, -32600, "Solicitud JSON-RPC inválida", 400)
    identity = body.get("id")
    if isinstance(identity, bool) or (
        identity is not None and not isinstance(identity, (str, int))
    ):
        return error(None, -32600, "Identificador inválido", 400)
    method = body["method"]
    params = body.get("params", {})
    if not isinstance(params, dict):
        return error(identity, -32602, "Parámetros inválidos")
    if "id" not in body:
        if method.startswith("notifications/"):
            return Response(status_code=202)
        return error(None, -32600, "El método requiere id", 400)
    version = request.headers.get("mcp-protocol-version", "2025-06-18")
    if method != "initialize" and version not in SUPPORTED:
        return error(identity, -32600, "Versión de protocolo no soportada", 400)
    if method == "initialize":
        selected = params.get("protocolVersion")
        result = {
            "protocolVersion": selected if selected in SUPPORTED else VERSION,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "drapemind", "version": settings.APP_VERSION},
        }
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        if params.get("cursor"):
            return error(identity, -32602, "Cursor desconocido")
        result = {
            "tools": [
                {
                    "name": tool["name"],
                    "description": tool["description"],
                    "inputSchema": tool["parameters"],
                    "annotations": {"readOnlyHint": True, "destructiveHint": False},
                }
                for tool in tool_catalog(user)
            ]
        }
    elif method == "tools/call":
        name = params.get("name")
        definition = TOOLS.get(name) if isinstance(name, str) else None
        arguments = params.get("arguments", {})
        if not definition or not definition.read_only:
            return error(identity, -32602, "Herramienta no disponible")
        from app.services.access_control import tool_allowed
        if not tool_allowed(definition, user, db):
            return error(identity, -32602, "Herramienta no disponible")
        if (
            not isinstance(arguments, dict)
            or set(arguments) - definition.args_model.model_fields.keys()
        ):
            return error(identity, -32602, "Argumentos desconocidos")
        try:
            data = await run_in_threadpool(
                execute_tool, name, arguments, ToolContext(db=db, user=user)
            )
        except HTTPException as exc:
            data = {"error": exc.detail}
        data = jsonable_encoder(data)
        result = {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(data, ensure_ascii=False, separators=(",", ":")),
                }
            ],
            "structuredContent": {"result": data},
            "isError": isinstance(data, dict) and bool(data.get("error")),
        }
    else:
        return error(identity, -32601, "Método no soportado")
    return JSONResponse(
        {"jsonrpc": "2.0", "id": identity, "result": result},
        headers={"Cache-Control": "private, no-store"},
    )
