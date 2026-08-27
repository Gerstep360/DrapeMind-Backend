"""Run one real Gemma Observe/Act cycle against the local catalog."""

import asyncio
import json

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models import User
from app.services.ai import _completion
from app.services.ai_agent import run_gemma_tool_agent
from app.services.model_runtime import model_runtime


async def main() -> None:
    db = SessionLocal()
    try:
        user = db.scalar(select(User).order_by(User.id).limit(1))
        if not user:
            raise RuntimeError("No hay usuarios para ejecutar el diagnóstico")
        async with model_runtime.lease():
            result = await run_gemma_tool_agent(
                db,
                user,
                "Revisa mis reservas y dime cuál de las activas vence primero.",
                {},
                _completion,
            )
        print(
            json.dumps(
                {
                    "tools": [step["name"] for step in result["composite_sub_tools"]],
                    "answer": result["direct_response"],
                    "cards": len(result["action_items"]),
                    "agent_mode": result["response_meta"].get("agent_mode"),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    finally:
        db.close()
        await model_runtime.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
