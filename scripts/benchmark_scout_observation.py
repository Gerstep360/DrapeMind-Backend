"""Live local model with explicit synthetic observations; no real customer data."""
import asyncio
import json
import time
from app.services.scout_orchestrator import scout_completion, scout_prompt, shutdown_scout
from app.services.context_prompt import build_messages
from app.services.chat_context import ChatContext
from app.services.ai_tools import tool_catalog


async def main():
    cases = [
        ('Busca alguna chaqueta por menos de 620 Bs', []),
        ('Busca alguna chaqueta por menos de 620 Bs', [
            {'tool': 'search_products', 'args': {'query': 'chaqueta', 'max_price': 620}, 'result': []}]),
    ]
    try:
        for message, observations in cases:
            start = time.monotonic()
            async with asyncio.timeout(75):
                result = await scout_completion(build_messages(scout_prompt(message, ChatContext(), tool_catalog(), observations)))
            print(json.dumps({'synthetic_observations': bool(observations), 'seconds': round(time.monotonic()-start,2),
                'decision': result['choices'][0]['message']['content']}, ensure_ascii=False), flush=True)
    finally:
        await shutdown_scout()


if __name__ == '__main__':
    asyncio.run(main())
