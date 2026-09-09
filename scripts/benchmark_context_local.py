"""Local CPU benchmark; fixture tools are explicit, never production data."""
import asyncio
import json
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock
import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core.config import settings
from app.services import ai_agent
from app.services.ai import _completion
from app.services.chat_context import ChatContext
from app.services.context_prompt import prompt_sections
from app.services.ai_tools import tool_catalog
from app.services.model_runtime import model_runtime

# Synthetic catalog, used only to evaluate reference continuity without network/database writes.
CATALOG = [
    {"id": 701, "nombre": "Camisa de lino", "precio": "180.00", "variante_id": 801, "talla": "M", "color": "Marfil", "stock": 3},
    {"id": 702, "nombre": "Chaqueta ligera", "precio": "320.00", "variante_id": 802, "talla": "M", "color": "Azul", "stock": 2},
    {"id": 703, "nombre": "Pantalón recto", "precio": "210.00", "variante_id": 803, "talla": "L", "color": "Gris", "stock": 4},
]


async def main():
    settings.AI_BASE_URL = "http://127.0.0.1:18088/v1"
    settings.AI_SERVER_HOST = "127.0.0.1"
    settings.AI_SERVER_PORT = 18088
    settings.AI_THREADS = 3
    settings.AI_CONTEXT_SIZE = 4096
    settings.AI_GPU_LAYERS = "0"
    settings.AI_SERVER_EXTRA_ARGS = ""
    settings.AI_CONTEXT_TOKEN_METRICS = True
    assert settings.AI_REASONING_BUDGET == 64, "Benchmark must preserve reasoning budget"
    original_tool = ai_agent.execute_tool
    original_cards = ai_agent._cards_from_tool
    calls = []
    def fixture_tool(name, args, context):
        calls.append({"name": name, "args": args})
        if name in {"search_products", "recommend_outfit", "get_new_arrivals"}:
            return CATALOG
        if name in {"get_product_detail", "get_stock", "get_branch_availability", "find_alternatives"}:
            chosen = args.get("product_id")
            return [p for p in CATALOG if p["id"] == chosen]
        if name == "get_my_cart":
            return {"items": CATALOG[:1], "total": "180.00"}
        return {"error": "Tool not represented by this benchmark fixture"}
    def fixture_cards(db, name, args, result):
        if isinstance(result, list):
            return [{**p, "accion": "AGREGAR"} for p in result if isinstance(p, dict) and "id" in p]
        return []
    ai_agent.execute_tool = fixture_tool
    ai_agent._cards_from_tool = fixture_cards
    records = []
    with open("logs/context-after.log", "w", encoding="utf8") as log:
        process = subprocess.Popen(model_runtime.command(), stdout=log, stderr=log,
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        try:
            async with httpx.AsyncClient(timeout=2) as client:
                for _ in range(90):
                    if process.poll() is not None: raise RuntimeError("Local runtime stopped")
                    try:
                        if (await client.get("http://127.0.0.1:18088/health")).status_code == 200: break
                    except httpx.HTTPError: pass
                    await asyncio.sleep(1)
                else: raise TimeoutError("Local startup")
            scenarios = [
                ("A", "Quiero algo para una cena, máximo 500 Bs."),
                ("A", "¿y el segundo?"),
                ("A", "¿hay algo parecido pero más barato?"),
                ("B", "¿Qué preferencias conoces de esta conversación?"),
                ("C", "Qué tengo en mi carrito, dime qué cambiarías y recomiéndame algo nuevo. Tengo un funeral en una hora."),
                ("A", "¿Hay alguna prenda específica en stock en la tienda más cercana?"),
            ]
            states = {}
            for chat, question in scenarios:
                calls.clear()
                parts = prompt_sections(question, ChatContext.model_validate(states.get(chat, {})), tool_catalog(), [])
                chunks = []
                first_content = None
                start = time.monotonic()
                async def complete(messages, **kwargs):
                    nonlocal first_content
                    async def on_text(value):
                        nonlocal first_content
                        if first_content is None: first_content = time.monotonic() - start
                    response = await _completion(messages, **kwargs, on_text=on_text, context_chat_id=chat)
                    chunks.append(response.get("context_metrics"))
                    return response
                record = {"chat": chat, "query": question, "tools_fixture": True}
                try:
                    result = await ai_agent.run_gemma_tool_agent(MagicMock(), SimpleNamespace(id=1), question,
                        states.get(chat, {}), complete, max_steps=4)
                    states[chat] = result["chat_context"]
                    record.update(answer=result["direct_response"], state=states[chat],
                                  ui=result["response_meta"].get("product_picker"),
                                  history_messages_sent=0)
                except Exception as exc:
                    record["error"] = str(exc)
                record.update(seconds=round(time.monotonic()-start, 3), first_content_seconds=first_content,
                              calls=list(calls), context_metrics=chunks)
                records.append(record)
                print(json.dumps(record, ensure_ascii=True), flush=True)
        finally:
            process.terminate()
            try: process.wait(timeout=10)
            except subprocess.TimeoutExpired: process.kill(); process.wait()
            ai_agent.execute_tool, ai_agent._cards_from_tool = original_tool, original_cards
    return records

if __name__ == "__main__":
    asyncio.run(main())
