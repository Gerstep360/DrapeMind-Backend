"""Consultar la disponibilidad del proveedor NVIDIA."""
import asyncio
from app.services.llm_provider import provider_status

if __name__ == '__main__':
    print(asyncio.run(provider_status()))
