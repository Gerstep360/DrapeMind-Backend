"""Opt-in local-only model benchmark. Never connects to the configured remote host."""
import asyncio
import ast
import json
import re
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core.config import settings
from app.services.ai import _completion
from app.services.ai_agent import run_gemma_tool_agent
from app.services.model_runtime import model_runtime


async def main():
    settings.AI_BASE_URL = "http://127.0.0.1:18088/v1"
    settings.AI_SERVER_HOST = "127.0.0.1"
    settings.AI_SERVER_PORT = 18088
    settings.AI_THREADS = 3
    settings.AI_CONTEXT_SIZE = 4096
    settings.AI_SERVER_EXTRA_ARGS = ""
    settings.AI_GPU_LAYERS = "0"
    log_path = Path(__file__).resolve().parents[1] / "logs" / "benchmark-local.log"
    with log_path.open("w", encoding="utf-8") as log:
        process = subprocess.Popen(model_runtime.command(), stdout=log, stderr=log,
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        try:
            for _ in range(90):
                if process.poll() is not None:
                    raise RuntimeError("Local model failed to start; see benchmark-local.log")
                if await model_runtime.is_healthy():
                    break
                await asyncio.sleep(1)
            else:
                raise TimeoutError("Local model startup")
            for question in [
                "Explícame brevemente qué funciones tienes como asistente.",
                "Escribe una función Python que sume dos cantidades de libros y un ejemplo de uso."
            ]:
                start = time.monotonic()
                first = None
                async def on_text(raw):
                    nonlocal first
                    if first is None:
                        first = round(time.monotonic() - start, 2)
                async def complete(messages, **kwargs):
                    response = await _completion(messages, **kwargs, on_text=on_text)
                    if "--protocol" in sys.argv:
                        print(json.dumps({"protocol": response}, ensure_ascii=True), flush=True)
                    return response
                result = await run_gemma_tool_agent(MagicMock(), SimpleNamespace(id=0), question, {}, complete)
                if "función Python" in question:
                    code = re.search(r"```python\s*\n(.*?)```", result["direct_response"], re.S)
                    if not code:
                        raise AssertionError("Code benchmark returned no Python implementation")
                    ast.parse(code.group(1))
                print(json.dumps({"seconds": round(time.monotonic()-start, 2), "first_content": first,
                                  "answer": result["direct_response"]}, ensure_ascii=True), flush=True)
            if "--database" in sys.argv:
                from sqlalchemy import select, text
                from app.db.session import engine, SessionLocal
                from app.models import User, Role
                if engine.url.host not in {"127.0.0.1", "localhost", "::1"}:
                    raise RuntimeError("Only a loopback database is permitted")
                with SessionLocal() as db:
                    db.execute(text("SET TRANSACTION READ ONLY"))
                    user = db.scalar(select(User).where(User.rol == Role.CLIENTE).limit(1))
                    if user is None:
                        raise RuntimeError("A local client is needed for the read-only tool check")
                    start = time.monotonic()
                    result = await run_gemma_tool_agent(db, user,
                        "Busca hasta dos prendas azules disponibles por menos de 400 Bs.", {}, complete)
                    print(json.dumps({"database_read_only": True, "seconds": round(time.monotonic()-start, 2),
                        "tools": [step["name"] for step in result["composite_sub_tools"]],
                        "answer": result["direct_response"]}, ensure_ascii=True), flush=True)
                    db.rollback()
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


if __name__ == "__main__":
    asyncio.run(main())
