"""Isolated local routing benchmark; does not execute tools or access the database."""
import asyncio
import json
import time
import sys
from app.services.scout_orchestrator import scout_completion, scout_prompt, shutdown_scout
from app.services.context_prompt import build_messages
from app.services.chat_context import ChatContext
from app.services.ai_tools import tool_catalog


async def main():
    try:
        for text in (sys.argv[1:] or ("Buenas", "Buen día", "Consulta los artículos que guardé en mi cesta")):
            started = time.monotonic()
            try:
                async with asyncio.timeout(75):
                    result = await scout_completion(build_messages(scout_prompt(text, ChatContext(), tool_catalog(), [])))
                print(json.dumps({"input": text, "seconds": round(time.monotonic()-started, 2),
                    "decision": result['choices'][0]['message']['content'], "usage": result.get('usage'),
                    "timings": result.get('timings')}, ensure_ascii=False), flush=True)
            except Exception as exc:
                print(json.dumps({"seconds": round(time.monotonic()-started, 2), "error": type(exc).__name__}), flush=True)
    finally:
        await shutdown_scout()


if __name__ == '__main__':
    asyncio.run(main())
