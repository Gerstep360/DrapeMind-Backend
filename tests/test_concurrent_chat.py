import asyncio

from fastapi import HTTPException
import pytest

from app.services.concurrent_chat import ConnectionTasks


@pytest.mark.asyncio
async def test_independent_question_finishes_while_search_continues():
    events = []
    gate = asyncio.Event()

    async def send(event):
        events.append(event)

    async def search(emit, context):
        await gate.wait()
        await emit({"type": "done", "content": "prendas"})

    async def policy(emit, context):
        assert context["pending"][0]["message"] == "camisas blancas"
        await emit({"type": "done", "content": "política"})

    manager = ConnectionTasks(send)
    first = await manager.submit("m1", 7, "camisas blancas", search)
    second = await manager.submit("m2", 7, "¿hacen envíos?", policy)
    await second.task
    assert not first.task.done()
    assert next(event for event in events if event["type"] == "done")["request_id"] == "m2"
    gate.set()
    await first.task
    assert [event["request_id"] for event in events if event["type"] == "done"] == ["m2", "m1"]
    assert not manager.jobs


@pytest.mark.asyncio
async def test_changed_filters_cancel_old_job_and_suppress_stale_results():
    events = []
    gate = asyncio.Event()

    async def send(event):
        events.append(event)

    async def obsolete(emit, context):
        try:
            await gate.wait()
        except asyncio.CancelledError:
            # Even a provider finishing late cannot send stale UI after cancellation.
            await emit({"type": "results", "action_items": ["white"]})
            raise

    manager = ConnectionTasks(send)
    first = await manager.submit("m1", 7, "blancas", obsolete)
    await asyncio.sleep(0)

    async def replacement(emit, context):
        result = await context["cancel"](first.task_id)
        assert result["cancelled"]
        await emit({"type": "results", "action_items": ["black"]})

    second = await manager.submit("m2", 7, "mejor negras", replacement)
    await second.task
    results = [event for event in events if event["type"] == "results"]
    assert len(results) == 1 and results[0]["request_id"] == "m2"
    assert any(event["type"] == "task_cancelled" and event["request_id"] == "m1" for event in events)
    assert results[0]["request_version"] > first.version


@pytest.mark.asyncio
async def test_limits_ownership_and_disconnect_cleanup():
    gate = asyncio.Event()

    async def send(event):
        pass

    async def wait(emit, context):
        await gate.wait()

    manager = ConnectionTasks(send, limit=2)
    first = await manager.submit("m1", 1, "consulta", wait)

    async def another_session(emit, context):
        assert context["pending"] == []
        assert (await context["cancel"](first.task_id))["cancelled"] is False
        await gate.wait()

    second = await manager.submit("m2", 2, "otra", another_session)
    await asyncio.sleep(0)
    with pytest.raises(HTTPException) as error:
        await manager.submit("m3", 1, "exceso", wait)
    assert error.value.status_code == 429
    await manager.close()
    assert first.task.cancelled() and second.task.cancelled()
    assert not manager.jobs
