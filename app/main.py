import logging
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.api.v1.router import api_router
from app.core.config import settings
from app.db.session import engine
from app.services.model_runtime import model_runtime
from app.services.realtime import websocket_origin_allowed

logger = logging.getLogger("drapemind")


@asynccontextmanager
async def lifespan(application: FastAPI):
    model_runtime.start_monitor()
    yield
    await model_runtime.shutdown()

tags_metadata = [
    {"name": "Autenticacion", "description": "Registro, login JWT y usuario actual."},
    {"name": "Catalogo y favoritos", "description": "Catalogo publico, busqueda, variantes y favoritos."},
    {"name": "Sucursales e inventario", "description": "Disponibilidad física por sede y configuración protegida de inventario."},
    {"name": "IA - Gemma", "description": "Gemma usa exclusivamente tools controlados por FastAPI; nunca conecta a PostgreSQL."},
    {"name": "Administracion", "description": "Operaciones protegidas por rol ADMIN o VENDEDOR segun endpoint."},
]

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description=(
        "Backend para tienda de ropa con IA y AR. Autenticacion Bearer JWT. "
        "Los precios, permisos, stock y transacciones siempre se validan en FastAPI."
    ),
    openapi_tags=tags_metadata,
    openapi_url=f"{settings.API_V1_PREFIX}/openapi.json" if settings.DOCS_ENABLED else None,
    docs_url="/docs" if settings.DOCS_ENABLED else None,
    redoc_url="/redoc" if settings.DOCS_ENABLED else None,
    root_path=settings.ROOT_PATH,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_origin_regex=settings.CORS_ORIGIN_REGEX,
    allow_credentials=settings.CORS_ALLOW_CREDENTIALS,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Accept", "X-Webhook-Signature", "X-Request-ID", "Idempotency-Key"],
    expose_headers=["X-Request-ID", "X-Process-Time-Ms"],
    max_age=600,
)


@app.middleware("http")
async def request_context(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    started = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        logger.exception("Unhandled error request_id=%s", request_id)
        response = JSONResponse(status_code=500, content={"detail": "Error interno", "request_id": request_id})
        origin = request.headers.get("Origin")
        if origin and websocket_origin_allowed(origin):
            response.headers["Access-Control-Allow-Origin"] = origin.rstrip("/")
            response.headers["Access-Control-Allow-Credentials"] = str(
                settings.CORS_ALLOW_CREDENTIALS
            ).lower()
            response.headers["Vary"] = "Origin"
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Process-Time-Ms"] = f"{(time.perf_counter() - started) * 1000:.2f}"
    return response


app.include_router(api_router, prefix=settings.API_V1_PREFIX)
STATIC_DIR = Path(__file__).resolve().parent / "static"
STATIC_DIR.mkdir(parents=True, exist_ok=True)

PLACEHOLDER_SVG_FALLBACK = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="800" height="1000" viewBox="0 0 800 1000" role="img">'
    '<defs><linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">'
    '<stop offset="0" stop-color="#10281f"/><stop offset="1" stop-color="#244d3e"/></linearGradient></defs>'
    '<rect width="800" height="1000" fill="url(#bg)"/>'
    '<circle cx="400" cy="410" r="168" fill="none" stroke="#c5ff3d" stroke-width="5"/>'
    '<path d="M310 330l90-48 90 48 72 110-73 44-24-43v221H335V441l-24 43-73-44z" fill="#f4f0e7" opacity=".96"/>'
    '<text x="400" y="760" text-anchor="middle" fill="#f4f0e7" font-family="Georgia,serif" font-size="62">DrapeMind</text>'
    '<text x="400" y="820" text-anchor="middle" fill="#c5ff3d" font-family="Arial,sans-serif" font-size="24" letter-spacing="8">ATELIER</text>'
    '<text x="400" y="900" text-anchor="middle" fill="#cbd3ce" font-family="Arial,sans-serif" font-size="22">Prenda en exhibición</text>'
    '</svg>'
)


@app.get("/static/products/placeholder.svg", include_in_schema=False)
@app.get("/DrapeMind/static/products/placeholder.svg", include_in_schema=False)
def get_product_placeholder():
    file_path = STATIC_DIR / "products" / "placeholder.svg"
    if file_path.exists():
        return FileResponse(str(file_path), media_type="image/svg+xml")
    return Response(content=PLACEHOLDER_SVG_FALLBACK, media_type="image/svg+xml")


app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
app.mount("/DrapeMind/static", StaticFiles(directory=str(STATIC_DIR)), name="drapemind_static")


@app.get("/", tags=["Sistema"], summary="Descubrir la API")
def root() -> dict:
    return {"service": settings.APP_NAME, "version": settings.APP_VERSION, "docs": "/docs", "api": settings.API_V1_PREFIX}


@app.get("/health/live", tags=["Sistema"], summary="Liveness")
def liveness() -> dict:
    return {"status": "ok"}


@app.get("/health/ready", tags=["Sistema"], summary="Readiness PostgreSQL")
def readiness():
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except SQLAlchemyError:
        return JSONResponse(status_code=503, content={"status": "not_ready", "database": "unavailable"})
    return {"status": "ready", "database": "ok"}


@app.get("/health/ai", tags=["Sistema"], summary="Estado del runtime Gemma")
async def ai_health():
    status_data = await model_runtime.status()
    return JSONResponse(
        status_code=200 if status_data["healthy"] else 503,
        content=status_data,
    )
