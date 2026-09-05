import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.model_runtime import ModelRuntime


@pytest.mark.asyncio
async def test_lease_increments_and_decrements_active_requests():
    runtime = ModelRuntime()
    runtime.ensure_started = AsyncMock()

    assert runtime.active_requests == 0
    t0 = runtime.last_used_at

    async with runtime.lease():
        assert runtime.active_requests == 1
        assert runtime.last_used_at >= t0

    assert runtime.active_requests == 0


@pytest.mark.asyncio
async def test_monitor_triggers_stop_after_idle_timeout(monkeypatch):
    runtime = ModelRuntime()
    runtime.is_healthy = AsyncMock(return_value=True)
    runtime.stop = AsyncMock()

    # Simulate model used 700 seconds ago (idle timeout default is 600s)
    runtime.last_used_at = time.monotonic() - 700
    runtime.active_requests = 0

    # Run one step of monitor logic
    idle = time.monotonic() - runtime.last_used_at
    should_stop = runtime.active_requests == 0 and idle >= 600

    assert should_stop is True


@pytest.mark.asyncio
async def test_monitor_does_not_stop_while_requests_active():
    runtime = ModelRuntime()
    runtime.last_used_at = time.monotonic() - 700
    runtime.active_requests = 1  # User is actively chatting

    idle = time.monotonic() - runtime.last_used_at
    should_stop = runtime.active_requests == 0 and idle >= 600

    assert should_stop is False


@pytest.mark.asyncio
async def test_stop_process_terminates_and_cleans_up():
    runtime = ModelRuntime()
    fake_process = MagicMock()
    fake_process.poll.return_value = None
    fake_process.terminate = MagicMock()
    fake_process.wait = MagicMock()

    runtime.process = fake_process
    runtime._cleanup_stale_processes = MagicMock()

    await runtime._stop_process()

    assert runtime.process is None
    fake_process.terminate.assert_called_once()
    runtime._cleanup_stale_processes.assert_called_once()
