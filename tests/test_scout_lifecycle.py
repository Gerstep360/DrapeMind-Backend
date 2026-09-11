import asyncio
import unittest
from unittest.mock import AsyncMock, patch
from fastapi import WebSocketDisconnect
from app.services import scout_orchestrator as scout
from app.services.chat_context import ChatContext
from app.services.context_prompt import build_messages, prompt_sections
from app.services.socket_turn import _connected_turn


class LifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_disconnect_cancels_generation(self):
        started = asyncio.Event()
        cancelled = asyncio.Event()
        async def work():
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()
        async def receive():
            await started.wait()
            raise WebSocketDisconnect()
        socket = AsyncMock()
        socket.receive_json.side_effect = receive
        with self.assertRaises(WebSocketDisconnect):
            await _connected_turn(socket, work(), AsyncMock())
        self.assertTrue(cancelled.is_set())

    async def test_queue_times_out_without_releasing_other_owner(self):
        lock = asyncio.Lock()
        await lock.acquire()
        with patch.object(scout, 'turn_lock', lock), patch.object(scout, 'QUEUE_WAIT_SECONDS', .01):
            with self.assertRaises(scout.ModelRuntimeError):
                async with scout.inference_turn():
                    self.fail('Should not enter occupied slot')
            self.assertTrue(lock.locked())
        lock.release()

    async def test_cancel_releases_admission(self):
        lock = asyncio.Lock()
        started = asyncio.Event()
        async def work():
            async with scout.inference_turn():
                started.set()
                await asyncio.Event().wait()
        with patch.object(scout, 'turn_lock', lock):
            task = asyncio.create_task(work())
            await started.wait()
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            self.assertFalse(lock.locked())

    def test_user_message_is_preserved(self):
        text = '  necesito información\ncon estos detalles  '
        messages = build_messages(prompt_sections(text, ChatContext(), [], []))
        self.assertEqual(messages[-1], {'role': 'user', 'content': text})


if __name__ == '__main__':
    unittest.main()
