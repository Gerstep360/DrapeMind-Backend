import asyncio
import unittest
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from fastapi import WebSocketDisconnect
from app.services import scout_orchestrator as scout
from app.services.chat_context import ChatContext
from app.services.context_prompt import build_messages, prompt_sections
from app.services.socket_turn import _connected_turn


class LifecycleTests(unittest.IsolatedAsyncioTestCase):
    def test_env_rejects_pasted_assignments_without_leaking_values(self):
        from scripts.migrate_ai_env import parse
        for text in ('SCOUT_BASE_URL="http://localhost:8089/v1" SCOUT_API_KEY="private-fixture"',
                     'AI_BASE_URL="[http://localhost](http://localhost)"'):
            with self.assertRaises(ValueError) as error:
                parse(text)
            self.assertNotIn('private-fixture', str(error.exception))
        self.assertEqual(parse('APP_NAME="A name with spaces"')['APP_NAME'], '"A name with spaces"')

    def test_outfit_rejects_invented_sizes_and_measurements(self):
        from app.services.argument_grounding import unsupported_filters
        from app.services.ai_tools import RecommendOutfitArgs
        invalid = unsupported_filters(RecommendOutfitArgs.model_json_schema(),
            {'occasion': 'casual', 'shoe_size': '200', 'measurements': {'user_chest': 70}},
            'Un conjunto con calzado menor a 200bs', {})
        self.assertEqual(set(invalid), {'occasion', 'shoe_size', 'measurements'})

    async def test_nonstream_completion_returns_generated_response(self):
        import httpx
        from app.services import ai
        payload = {'choices': [{'message': {'content': 'Respuesta de prueba'}, 'finish_reason': 'stop'}]}
        client = AsyncMock()
        client.post.return_value = httpx.Response(200, json=payload, request=httpx.Request('POST', 'http://localhost/test'))
        with patch.object(ai.httpx, 'AsyncClient', return_value=client), patch.object(ai, 'context_metrics', AsyncMock()), patch.object(ai.ai_logger, 'log_gemma_inference') as log:
            result = await ai._completion([{'role': 'user', 'content': 'Consulta de prueba'}], stream=False)
        self.assertEqual(result, payload)
        self.assertGreaterEqual(log.call_args.kwargs['total_seconds'], 0)
        client.aclose.assert_awaited_once()

    async def test_missing_input_skips_scout_replanning(self):
        completion = AsyncMock(return_value={'choices': [{'message': {'content': json.dumps({
            'type': 'finish', 'answer': '¿Qué talla necesitas?'})}}]})
        async def fake_agent(*args, **kwargs):
            result = await kwargs['after_tool']({}, 'Necesito un conjunto', ChatContext(),
                [{'tool': 'recommend_outfit', 'result': {'status': 'needs_input', 'missing_fields': ['size']}}], [])
            return {'response_meta': {}, 'notices': [], 'composite_sub_tools': [], 'direct_response': result['answer']}
        gemma = AsyncMock(return_value={'choices': [{'message': {'content': '¿Qué talla necesitas?'}}]})
        from contextlib import asynccontextmanager
        @asynccontextmanager
        async def lease():
            yield
        with patch.object(scout, 'scout_completion', completion), patch.object(scout, 'run_gemma_tool_agent', fake_agent), patch.object(scout.model_runtime, 'lease', lease):
            await scout.run_scout_orchestrator(None, SimpleNamespace(id=1), 'Necesito un conjunto', {}, gemma, AsyncMock(), 1)
        completion.assert_not_awaited()
        gemma.assert_awaited_once()
        self.assertNotIn('get_my_cart(', gemma.call_args.args[0][0]['content'])

    def test_deploy_migration_adds_flag_preserves_custom_values(self):
        import tempfile
        from pathlib import Path
        from scripts.migrate_ai_env import migrate, parse
        with tempfile.TemporaryDirectory() as directory:
            env = Path(directory) / '.env'
            env.write_text('SCOUT_THREADS=2\nJWT_SECRET=fixture-only\n', encoding='utf-8')
            migrate(env)
            values = parse(env.read_text(encoding='utf-8'))
            self.assertEqual(values['SCOUT_COMPACT_CLARIFICATIONS'], 'true')
            self.assertEqual(values['SCOUT_THREADS'], '2')
            self.assertEqual(values['JWT_SECRET'], 'fixture-only')
            env.write_text(env.read_text().replace('SCOUT_COMPACT_CLARIFICATIONS=true', 'SCOUT_COMPACT_CLARIFICATIONS=false'))
            migrate(env)
            self.assertEqual(parse(env.read_text())['SCOUT_COMPACT_CLARIFICATIONS'], 'false')

    def test_unrequested_filters_rejected(self):
        from app.services.argument_grounding import unsupported_filters
        from app.services.ai_tools import SearchProductsArgs
        schema = SearchProductsArgs.model_json_schema()
        self.assertEqual(unsupported_filters(schema, {'color': 'negro', 'category_id': 1},
                                            'Quiero una chaqueta por 620 Bs', {}), ['category_id', 'color'])
        self.assertEqual(unsupported_filters(schema, {'color': 'azul'}, 'Busco algo azul', {}), [])

    async def test_duplicate_stops_planner_cycle(self):
        from app.services import ai_agent
        decision = {'type': 'tool', 'tool': 'search_products', 'arguments': {'query': 'chaqueta'}}
        complete = AsyncMock(return_value={'choices': [{'message': {'content': json.dumps(decision)}}]})
        delegate = AsyncMock(return_value='No hay coincidencias en esta búsqueda.')
        with patch.object(ai_agent, 'execute_tool', return_value=[]) as execute, patch.object(ai_agent, '_cards_from_tool', return_value=[]):
            result = await ai_agent.run_gemma_tool_agent(None, SimpleNamespace(id=1), 'Busca una chaqueta', {},
                                                      complete, delegate=delegate)
        self.assertEqual(complete.await_count, 2)
        execute.assert_called_once()
        delegate.assert_awaited_once()
        self.assertIn('No hay coincidencias', result['direct_response'])

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
