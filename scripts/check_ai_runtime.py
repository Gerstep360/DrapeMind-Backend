"""Start, report and stop the managed Gemma runtime for local diagnostics."""

import asyncio
import json

from app.services.model_runtime import model_runtime


async def main() -> None:
    try:
        await model_runtime.ensure_started()
        print(json.dumps(await model_runtime.status(), indent=2))
    finally:
        await model_runtime.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
