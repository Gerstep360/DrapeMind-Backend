"""
DRAPEMIND ATELIER - SUITE DE SCRIPTS ORGANIZADOS
- scripts.ai: Descarga rápida de modelos GGUF, diagnóstico de runtime y protocolos.
- scripts.db: Semillas de datos, administración visual de base de datos y usuarios.
- scripts.diagnostics: Verificación de casos de uso y pruebas E2E.
"""

from .ai.download_models import (
    DEFAULT_MODELS,
    check_models_status,
    download_file_fast,
    format_bytes,
    format_speed,
)

__all__ = [
    "DEFAULT_MODELS",
    "check_models_status",
    "download_file_fast",
    "format_bytes",
    "format_speed",
]
