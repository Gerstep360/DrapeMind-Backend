import asyncio
from contextlib import suppress
from fastapi import WebSocketDisconnect


async def _connected_turn(socket, operation, send):
    """Cancel abandoned inference while continuing to answer heartbeats."""
    task = asyncio.create_task(operation)
    reader = asyncio.create_task(socket.receive_json())
    try:
        while True:
            done, _ = await asyncio.wait({task, reader}, return_when=asyncio.FIRST_COMPLETED)
            if reader in done:
                event = reader.result()
                if event.get("type") == "ping":
                    await send({"type": "pong"})
                else:
                    await send({"type": "busy", "message": "Hay una consulta en curso."})
                reader = asyncio.create_task(socket.receive_json())
            if task in done:
                return await task
    finally:
        for pending in (reader, task):
            if not pending.done():
                pending.cancel()
        for pending in (reader, task):
            with suppress(asyncio.CancelledError, WebSocketDisconnect, RuntimeError):
                await pending
