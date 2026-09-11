"""Live compact clarification using Gemma, with synthetic tools and no database access."""
import asyncio
import json
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from app.services import scout_orchestrator as scout
from app.services.chat_context import ChatContext
from app.services.ai import _completion


async def main():
    original = scout.scout_completion
    measurements = []
    async def measured(*args, **kwargs):
        response = await original(*args, **kwargs)
        measurements.append(response.get('usage', {}))
        return response
    async def tool_fixture(db, user, message, memory, *args, **kwargs):
        result = await kwargs['after_tool']({}, message, ChatContext(constraints={'top_size': 'M'}),
            [{'tool': 'recommend_outfit', 'result': {'status': 'needs_input',
             'missing_fields': ['bottom_size', 'occasion']}}], [])
        return {'response_meta': {}, 'notices': [], 'composite_sub_tools': [], 'direct_response': result['answer']}
    try:
        with patch.object(scout, 'scout_completion', measured), patch.object(scout, 'run_gemma_tool_agent', tool_fixture):
            for message in ('Combina mi camisa M para salir, hasta 650 Bs.',
                            'Combina mi camisa M. Hasta 650 Bs, pero si hay botas caras puedo aumentar a 900 Bs.'):
                start = time.monotonic()
                async def gemma(*args, **kwargs):
                    response = await _completion(*args, **kwargs)
                    measurements.append(response.get('usage', {}))
                    return response
                result = await scout.run_scout_orchestrator(None, SimpleNamespace(id=0), message, {}, gemma, AsyncMock(), 0)
                print(json.dumps({'seconds': round(time.monotonic()-start,2), 'usage': measurements[-1],
                                  'answer': result['direct_response'], 'synthetic_tools': True}, ensure_ascii=False), flush=True)
    finally:
        await scout.shutdown_scout()
        await scout.model_runtime.shutdown()


if __name__ == '__main__':
    asyncio.run(main())
