"""Real local API smoke check with a disposable account; never prints credentials."""
import asyncio
import secrets
from uuid import uuid4
import httpx
import websockets
from sqlalchemy import delete
from app.db.session import SessionLocal
from app.models import User

async def main():
    user_id = None
    async with httpx.AsyncClient(base_url='http://127.0.0.1:8000/api/v1', timeout=120) as client:
        try:
            credentials = {'email': f'qa-altair-{uuid4().hex}@example.com', 'password': secrets.token_urlsafe(24)}
            registered = await client.post('/auth/register', json={**credentials,'nombre':'Verificación local Altair'})
            registered.raise_for_status()
            user_id = registered.json()['id']
            login = await client.post('/auth/login', json=credentials)
            login.raise_for_status()
            print('Login real: HTTP', login.status_code)
            token = login.json()['access_token']
            client.headers['Authorization'] = f'Bearer {token}'
            notifications = await client.get('/notifications?limit=50')
            notifications.raise_for_status()
            print('Notificaciones: HTTP', notifications.status_code)
            profile = await client.post('/users/me/style-profile', json={
                'genero':'UNISEX','estilos_preferidos':['casual'],'talla_superior':'M',
                'infer_style':True,'infer_outfit':False,
            })
            profile.raise_for_status()
            assert profile.json().get('adn_estilo_ia') and not profile.json().get('inferencia_error')
            print('Perfil + inferencia NVIDIA: correctos')
            async with websockets.connect('ws://127.0.0.1:8000/api/v1/ws/ai', origin='http://localhost:4200') as socket:
                await socket.send(__import__('json').dumps({'type':'auth','token':token}))
                connected = __import__('json').loads(await socket.recv())
                assert connected['type']=='connected'
                await socket.send(__import__('json').dumps({'type':'chat','request_id':'local-smoke','message':'Busca hasta dos prendas disponibles de menos de 500 Bs. Consulta el catálogo real.'}))
                tools, answer, cards = [], '', []
                async with asyncio.timeout(120):
                    while True:
                        event = __import__('json').loads(await socket.recv())
                        if event['type']=='error': raise RuntimeError(event.get('message','Error de chat'))
                        if event['type']=='tool_start': tools.append(event['name'])
                        if event['type']=='answer_snapshot': answer=event.get('content','')
                        if event['type']=='done':
                            cards=event.get('action_items',[])
                            break
                assert answer and tools
                print('WebSocket NVIDIA real: respuesta recibida; herramientas:', ', '.join(tools), '; tarjetas:', len(cards))
        finally:
            if user_id is not None:
                with SessionLocal() as db:
                    db.execute(delete(User).where(User.id == user_id))
                    db.commit()
                print('Cuenta de comprobación eliminada; datos existentes conservados.')

if __name__=='__main__': asyncio.run(main())
