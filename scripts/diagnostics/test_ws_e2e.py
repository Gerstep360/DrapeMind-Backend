import asyncio
import json
import httpx
import websockets

async def test_ai_ws():
    # 1. Login
    async with httpx.AsyncClient() as client:
        res = await client.post(
            'http://127.0.0.1:8000/api/v1/auth/login',
            json={'email': 'admin@drapemind.com', 'password': 'admin123'}
        )
        print('Login status:', res.status_code)
        if res.status_code != 200:
            print('Login error:', res.text)
            return
        token = res.json()['access_token']

    # 2. Connect to WS
    uri = 'ws://127.0.0.1:8000/api/v1/ws/ai'
    async with websockets.connect(uri) as ws:
        # Send Auth
        await ws.send(json.dumps({'type': 'auth', 'token': token}))
        conn_event = json.loads(await ws.recv())
        print('Auth response:', conn_event)

        test_messages = [
            'Hola Altair',
            'Mira mi carrito y dime que puedo quitar o que puedo combinar en mi eleccion',
            'Arma un outfit elegante para una cena de gala con presupuesto de 800 Bs',
            'Busco camisas de lino blanco en talla M',
            'Cobré mi sueldo y quiero comprar algo de calidad',
        ]

        for msg in test_messages:
            print(f'\n--- TEST MSG: {msg} ---')
            await ws.send(json.dumps({'type': 'chat', 'message': msg, 'session_id': 99999}))
            
            tokens_count = 0
            while True:
                raw = await asyncio.wait_for(ws.recv(), timeout=60.0)
                evt = json.loads(raw)
                t = evt.get('type')
                if t == 'thought':
                    print('  [thought]', evt.get('content'))
                elif t == 'token':
                    tokens_count += 1
                elif t == 'presentation':
                    print('  [presentation] title:', evt.get('title'), 'cards:', evt.get('card_count'))
                elif t == 'error':
                    print('  [ERROR]:', evt.get('message'))
                    break
                elif t == 'done':
                    print(f'  [done] duration: {evt.get("duration_ms")}ms, tokens: {tokens_count}, tools: {evt.get("tools")}')
                    break

if __name__ == '__main__':
    asyncio.run(test_ai_ws())
