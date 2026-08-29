"""Diagnóstico reproducible de autenticación y chat por WebSocket."""

import argparse
import asyncio
import json

import httpx
import websockets
from websockets.exceptions import ConnectionClosed


async def _receive_json(socket, timeout: float = 20.0) -> dict:
    raw = await asyncio.wait_for(socket.recv(), timeout=timeout)
    return json.loads(raw)


async def check_invalid_token(ws_base: str) -> None:
    try:
        async with websockets.connect(f"{ws_base}/ai") as socket:
            await socket.send(json.dumps({"type": "auth", "token": "expired-or-corrupt"}))
            event = await _receive_json(socket)
            assert event.get("type") == "error", event
            assert event.get("code") == "AUTH_INVALID", event
            try:
                await socket.recv()
            except ConnectionClosed as exc:
                assert exc.code == 4401, exc
    except ConnectionClosed as exc:
        assert exc.code == 4401, exc
    print("OK token inválido: AUTH_INVALID + cierre 4401")


async def login(api_base: str, email: str, password: str) -> str:
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(
            f"{api_base}/auth/login",
            json={"email": email, "password": password},
        )
        response.raise_for_status()
        return response.json()["access_token"]


async def check_events(ws_base: str, token: str) -> None:
    async with websockets.connect(f"{ws_base}/events") as socket:
        await socket.send(json.dumps({"type": "auth", "token": token}))
        connected = await _receive_json(socket)
        assert connected == {"type": "connected", "channel": "events"}, connected
        await socket.send(json.dumps({"type": "ping"}))
        pong = await _receive_json(socket)
        assert pong.get("type") == "pong", pong
    print("OK /ws/events: autenticación y heartbeat")


async def check_ai(ws_base: str, token: str, message: str, timeout: float) -> None:
    async with websockets.connect(f"{ws_base}/ai", max_size=4 * 1024 * 1024) as socket:
        await socket.send(json.dumps({"type": "auth", "token": token}))
        connected = await _receive_json(socket)
        assert connected == {"type": "connected", "channel": "ai"}, connected
        await socket.send(
            json.dumps({"type": "chat", "message": message, "session_id": None})
        )

        event_types: list[str] = []
        streamed_text = ""
        while True:
            event = await _receive_json(socket, timeout)
            event_type = str(event.get("type", "unknown"))
            event_types.append(event_type)
            if event_type == "token":
                streamed_text += str(event.get("content", ""))
            if event_type == "error":
                raise RuntimeError(event.get("message", "Error de chat sin detalle"))
            if event_type == "done":
                assert event.get("session_id") is not None, event
                break

    assert "done" in event_types
    assert "presentation" in event_types
    print(
        "OK /ws/ai: "
        f"{len(event_types)} eventos, {len(streamed_text)} caracteres en streaming"
    )


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--email", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument(
        "--message",
        default="Muéstrame una chaqueta impermeable talla XL por menos de Bs 900.",
    )
    parser.add_argument("--timeout", type=float, default=180.0)
    args = parser.parse_args()

    api_base = f"{args.base_url.rstrip('/')}/api/v1"
    ws_base = (
        api_base.replace("http://", "ws://").replace("https://", "wss://")
        + "/ws"
    )
    await check_invalid_token(ws_base)
    token = await login(api_base, args.email, args.password)
    await check_events(ws_base, token)
    await check_ai(ws_base, token, args.message, args.timeout)


if __name__ == "__main__":
    asyncio.run(main())
