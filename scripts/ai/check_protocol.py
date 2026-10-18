"""Comprobar el contrato de herramientas y streaming de NVIDIA."""
import asyncio
from app.services.llm_provider import check_provider

if __name__ == '__main__':
    result = asyncio.run(check_provider())
    print('NVIDIA:', result['model'], 'herramientas y streaming comprobados')
