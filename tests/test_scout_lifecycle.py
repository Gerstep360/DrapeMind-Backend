import asyncio
import unittest
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
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

    def test_outfit_args_supports_base_product_id(self):
        from app.services.ai_tools import RecommendOutfitArgs
        args = RecommendOutfitArgs(base_product_id=4, top_size="L", bottom_size="M")
        self.assertEqual(args.base_product_id, 4)
        self.assertEqual(args.top_size, "L")
        self.assertEqual(args.bottom_size, "M")

    async def test_outfit_sanitizes_unsupported_filters_without_aborting(self):
        from app.services import ai_agent
        decision = {'type': 'tool', 'tool': 'recommend_outfit', 'arguments': {
            'occasion': 'casual', 'top_size': 'L', 'bottom_size': 'M', 'shoe_size': '44', 'max_budget': 1000
        }}
        complete = AsyncMock(side_effect=[
            {'choices': [{'message': {'content': json.dumps(decision)}}]},
            {'choices': [{'message': {'content': json.dumps({'type': 'finish', 'answer': 'Outfit listo'})}}]}
        ])
        mock_result = {
            'ocasion': 'casual', 'tops_sugeridos': [{'id': 1, 'nombre': 'Polera', 'precio': 100}],
            'inferiores_sugeridos': [{'id': 2, 'nombre': 'Pantalón', 'precio': 200}],
            'calzado_sugerido': [{'id': 3, 'nombre': 'Calzado', 'precio': 300}],
            'complementos_abrigos': [],
        }
        with patch.object(ai_agent, 'execute_tool', return_value=mock_result) as exec_mock, patch.object(ai_agent, '_cards_from_tool', return_value=[]):
            # Message does not mention 'casual', so 'occasion' is ungrounded
            result = await ai_agent.run_gemma_tool_agent(
                MagicMock(), SimpleNamespace(id=1),
                'polera en talla L, pantalon en talla M, calzado talla 44, presupuesto máximo de Bs 1000',
                {}, complete, max_steps=2
            )
        exec_mock.assert_called_once()
        called_args = exec_mock.call_args[0][1]
        self.assertNotIn('occasion', called_args)
        self.assertEqual(called_args.get('top_size'), 'L')
    def test_recommend_outfit_execution_returns_complete_outfit(self):
        from app.services.ai_tools import _recommend_outfit, RecommendOutfitArgs, ToolContext
        db = MagicMock()
        user = SimpleNamespace(id=1)
        mock_candidates = [
            {"id": 4, "nombre": "Polera Gráfica Edición Limitada Atelier", "precio": 179.0, "categoria_id": 1, "genero_objetivo": "UNISEX"},
            {"id": 10, "nombre": "Pantalón Sastrero Atelier", "precio": 289.0, "categoria_id": 2, "genero_objetivo": "UNISEX"},
            {"id": 20, "nombre": "Mocasín Cuero Atelier", "precio": 349.0, "categoria_id": 3, "genero_objetivo": "UNISEX"},
        ]
        var_top = SimpleNamespace(id=101, producto_id=4, color="Blanco Crudo", talla="L", imagen=None, stock_total=10, stock_reservado=0, activo=True)
        var_bottom = SimpleNamespace(id=102, producto_id=10, color="Negro", talla="M", imagen=None, stock_total=5, stock_reservado=0, activo=True)
        var_shoe = SimpleNamespace(id=103, producto_id=20, color="Negro", talla="44", imagen=None, stock_total=3, stock_reservado=0, activo=True)
        
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = [var_top, var_bottom, var_shoe]
        db.scalars.return_value = scalars_mock

        with patch("app.services.ai_tools.search_products", return_value=mock_candidates):
            raw_args = RecommendOutfitArgs(top_size="L", bottom_size="M", shoe_size="44", max_budget=1000)
            res = _recommend_outfit(ToolContext(db=db, user=user), raw_args)

        self.assertIn("tops_sugeridos", res)
        self.assertIn("inferiores_sugeridos", res)
        self.assertIn("calzado_sugerido", res)
        self.assertEqual(res["tops_sugeridos"][0]["nombre"], "Polera Gráfica Edición Limitada Atelier")
        self.assertEqual(res["inferiores_sugeridos"][0]["nombre"], "Pantalón Sastrero Atelier")
        self.assertEqual(res["calzado_sugerido"][0]["nombre"], "Mocasín Cuero Atelier")

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

    async def test_mini_uses_generated_text_without_gemma(self):
        generated = 'Texto único devuelto por el modelo de prueba.'
        completion = AsyncMock(return_value={
            'choices': [{'message': {'content': generated}, 'finish_reason': 'stop'}],
            'usage': {'prompt_tokens': 21, 'completion_tokens': 9},
        })
        async def fake_agent(*args, **kwargs):
            answer = await kwargs['delegate']('Consulta completa', ChatContext(), [])
            return {'response_meta': {}, 'notices': [], 'direct_response': answer}
        gemma = AsyncMock()
        with patch.object(scout, 'run_gemma_tool_agent', fake_agent), patch.object(scout, 'scout_text_completion', completion), patch.object(scout.model_runtime, 'lease') as main_lease:
            result = await scout.run_scout_orchestrator(None, SimpleNamespace(id=1),
                'Consulta completa', {}, gemma, AsyncMock(), 10, allow_delegation=False)
        self.assertEqual(result['direct_response'], generated)
        self.assertEqual(result['response_meta']['scout_calls'], 1)
        self.assertEqual(result['response_meta']['gemma_calls'], 0)
        self.assertEqual(completion.call_args.args[0][-1]['content'], 'Consulta completa')
        gemma.assert_not_awaited()
        main_lease.assert_not_called()

    async def test_mini_failure_is_not_replaced_with_template(self):
        async def fake_agent(*args, **kwargs):
            return await kwargs['delegate']('Consulta', ChatContext(), [])
        with patch.object(scout, 'run_gemma_tool_agent', fake_agent), patch.object(scout, 'scout_text_completion', AsyncMock(side_effect=scout.ModelRuntimeError('fallo'))):
            with self.assertRaises(scout.ModelRuntimeError):
                await scout.run_scout_orchestrator(None, SimpleNamespace(id=1),
                    'Consulta', {}, AsyncMock(), AsyncMock(), 10, allow_delegation=False)

    async def test_mini_observe_can_continue_searching(self):
        async def fake_agent(*args, **kwargs):
            outcome = await kwargs['after_tool']({'after': 'observe'}, 'Consulta', ChatContext(),
                [{'tool': 'get_my_cart', 'result': {'items': []}}], [])
            self.assertIsNone(outcome)
            return {'response_meta': {}, 'notices': []}
        with patch.object(scout, 'run_gemma_tool_agent', fake_agent):
            await scout.run_scout_orchestrator(None, SimpleNamespace(id=1),
                'Consulta', {}, AsyncMock(), AsyncMock(), 10, allow_delegation=False)

    async def test_mini_prose_request_has_no_tool_schema(self):
        import httpx
        from contextlib import asynccontextmanager
        @asynccontextmanager
        async def lease():
            yield
        client = AsyncMock()
        result = {'choices': [{'message': {'content': 'Texto generado'}, 'finish_reason': 'stop'}]}
        client.__aenter__.return_value = client
        client.post.return_value = httpx.Response(200, json=result, request=httpx.Request('POST', 'http://localhost/test'))
        with patch.object(scout, 'scout_runtime', return_value=SimpleNamespace(lease=lease)), patch.object(scout.httpx, 'AsyncClient', return_value=client):
            actual = await scout.scout_text_completion([{'role': 'user', 'content': 'Hola'}])
        self.assertEqual(actual, result)
        payload = client.post.call_args.kwargs['json']
        self.assertNotIn('response_format', payload)
        self.assertNotIn('tools', payload)
        self.assertTrue(payload['cache_prompt'])


if __name__ == '__main__':
    unittest.main()
