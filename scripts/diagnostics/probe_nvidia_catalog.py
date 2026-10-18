"""Measure one configured NVIDIA model against the real read-only catalog tools.

Overrides the model for this process only; never edits .env or prints credentials.
"""
import argparse
import asyncio
import secrets
import time
from uuid import uuid4

import httpx
from sqlalchemy import delete

from app.core.config import settings
from app.db.session import SessionLocal
from app.models import User
from app.services.nvidia_agent import run_nvidia_agent
from app.services.ai_errors import AIProviderError


async def main(model):
    settings.NVIDIA_MODEL = model
    identity = None
    async with httpx.AsyncClient(base_url='http://127.0.0.1:8000/api/v1',timeout=15) as api:
        try:
            response = await api.post('/auth/register',json={
                'email':f'qa-model-{uuid4().hex}@example.com','password':secrets.token_urlsafe(24),'nombre':'Prueba de catálogo'})
            response.raise_for_status()
            identity = response.json()['id']
            async def emit(event):
                if event['type']=='tool_start': print('Tool:',event['name'],flush=True)
            started = time.perf_counter()
            with SessionLocal() as db:
                result = await run_nvidia_agent(db,db.get(User,identity),
                    'Muéstrame dos novedades del catálogo real para elegir. Quiero ver las prendas.',{},emit)
                print('Modelo:',model,'segundos:',round(time.perf_counter()-started,1),
                      'productos verificados:',len(result['verified_products']),'tarjetas:',len(result['action_items']),flush=True)
                assert len(result['action_items']) == 2
        finally:
            if identity is not None:
                with SessionLocal() as db:
                    db.execute(delete(User).where(User.id==identity))
                    db.commit()
                print('Cuenta temporal eliminada.',flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model',default=settings.NVIDIA_MODEL)
    args=parser.parse_args()
    try:
        asyncio.run(main(args.model))
    except Exception as exc:
        print('Prueba fallida:',type(exc).__name__)
        if isinstance(exc, AIProviderError): print(str(exc))
        cause = exc.__cause__
        if isinstance(cause, httpx.HTTPStatusError):
            body = cause.response.text.lower()
            print('Indicadores de diagnóstico:', [word for word in ('temperature','max_tokens','chat_template_kwargs','tools','tool_choice','enable_thinking','model','not found','unsupported','reasoning_budget') if word in body])
        raise SystemExit(1)
