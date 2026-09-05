import asyncio
import os
import shlex
import shutil
import subprocess
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

import httpx

from app.core.config import settings

BACKEND_DIR = Path(__file__).resolve().parents[2]


class ModelRuntimeError(RuntimeError):
    pass


class ModelRuntime:
    """Manages a local llama-server process and unloads it after idle time."""

    def __init__(self) -> None:
        self.process: subprocess.Popen | None = None
        self.active_requests = 0
        self.last_used_at = 0.0
        self.started_at: float | None = None
        self._start_lock = asyncio.Lock()
        self._state_lock = asyncio.Lock()
        self._monitor_task: asyncio.Task | None = None
        self._log_handle = None

    def _resolve_path(self, value: str) -> Path:
        path = Path(value)
        return path if path.is_absolute() else BACKEND_DIR / path

    def executable(self) -> Path | None:
        if settings.LLAMA_SERVER_PATH:
            configured = self._resolve_path(settings.LLAMA_SERVER_PATH)
            if configured.exists():
                return configured
        local_windows = BACKEND_DIR / "vendor" / "llama.cpp" / "llama-server.exe"
        if os.name == "nt" and local_windows.exists():
            return local_windows

        linux_candidates = [
            Path("/usr/local/bin/llama-server"),
            Path("/usr/bin/llama-server"),
            Path("/opt/llama.cpp/build/bin/llama-server"),
            BACKEND_DIR / "vendor" / "llama.cpp" / "llama-server",
        ]
        for candidate in linux_candidates:
            if candidate.exists() and os.access(candidate, os.X_OK):
                return candidate

        found = shutil.which("llama-server") or shutil.which("llama-server.exe")
        return Path(found) if found else None

    def model_path(self) -> Path:
        return self._resolve_path(settings.AI_MODEL_PATH)

    def mmproj_path(self) -> Path | None:
        if not settings.AI_MMPROJ_PATH:
            return None
        path = self._resolve_path(settings.AI_MMPROJ_PATH)
        return path if path.exists() else None

    async def is_healthy(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                response = await client.get(f"{settings.AI_BASE_URL.rstrip('/')}/models")
                return response.status_code < 500
        except httpx.HTTPError:
            return False

    def command(self) -> list[str]:
        executable = self.executable()
        model = self.model_path()
        if not executable:
            raise ModelRuntimeError(
                "llama-server no encontrado. Configure LLAMA_SERVER_PATH en el VPS Linux."
            )
        if not model.exists():
            raise ModelRuntimeError(f"Modelo GGUF no encontrado: {model}")
        command = [
            str(executable),
            "--model", str(model),
            "--alias", settings.AI_MODEL,
            "--host", settings.AI_SERVER_HOST,
            "--port", str(settings.AI_SERVER_PORT),
            "--ctx-size", str(settings.AI_CONTEXT_SIZE),
            "--parallel", str(settings.AI_PARALLEL_SLOTS),
            "--n-gpu-layers", settings.AI_GPU_LAYERS,
        ]
        mmproj = self.mmproj_path()
        if mmproj:
            command.extend(["--mmproj", str(mmproj)])
        if settings.AI_THREADS > 0:
            command.extend(["--threads", str(settings.AI_THREADS)])
        if settings.AI_SERVER_EXTRA_ARGS:
            command.extend(shlex.split(settings.AI_SERVER_EXTRA_ARGS, posix=os.name != "nt"))
        return command

    async def ensure_started(self) -> None:
        if await self.is_healthy():
            self.last_used_at = time.monotonic()
            return
        if not settings.AI_MANAGED_SERVER:
            raise ModelRuntimeError(
                "El servidor de IA no responde y AI_MANAGED_SERVER esta desactivado."
            )
        async with self._start_lock:
            if await self.is_healthy():
                self.last_used_at = time.monotonic()
                return
            if self.process and self.process.poll() is None:
                await self._wait_until_healthy()
                return
            command = self.command()
            log_dir = BACKEND_DIR / "logs"
            log_dir.mkdir(exist_ok=True)
            self._log_handle = (log_dir / "llama-server.log").open("ab")
            creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
            # Uvicorn --reload uses a Windows selector loop that doesn't implement
            # asyncio subprocesses. Popen is portable; only wait() goes to a thread.
            self.process = subprocess.Popen(
                command,
                cwd=str(self.executable().parent),
                stdout=self._log_handle,
                stderr=subprocess.STDOUT,
                creationflags=creationflags,
            )
            self.started_at = time.monotonic()
            self.last_used_at = self.started_at
            await self._wait_until_healthy()

    async def _wait_until_healthy(self) -> None:
        deadline = time.monotonic() + settings.AI_STARTUP_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            if self.process and self.process.poll() is not None:
                await self._stop_process()
                raise ModelRuntimeError(
                    "llama-server termino durante el arranque. Revise logs/llama-server.log"
                )
            if await self.is_healthy():
                return
            await asyncio.sleep(1.0)
        # ensure_started owns _start_lock while waiting. Cleaning up here must not
        # reacquire that same lock or a failed startup would deadlock forever.
        await self._stop_process()
        raise ModelRuntimeError(
            "Gemma no estuvo listo antes del timeout. Revise logs/llama-server.log"
        )

    @asynccontextmanager
    async def lease(self) -> AsyncIterator[None]:
        await self.ensure_started()
        async with self._state_lock:
            self.active_requests += 1
            self.last_used_at = time.monotonic()
        try:
            yield
        finally:
            async with self._state_lock:
                self.active_requests = max(0, self.active_requests - 1)
                self.last_used_at = time.monotonic()

    async def _stop_process(self) -> None:
        process = self.process
        self.process = None
        self.started_at = None
        if process and process.poll() is None:
            process.terminate()
            try:
                await asyncio.to_thread(process.wait, 10)
            except subprocess.TimeoutExpired:
                process.kill()
                await asyncio.to_thread(process.wait)
        # Kill any orphaned llama-server process on Windows if still running
        if os.name == "nt":
            try:
                subprocess.run(
                    ["taskkill", "/F", "/IM", "llama-server.exe"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except Exception:
                pass
        if self._log_handle:
            self._log_handle.close()
            self._log_handle = None

    async def stop(self) -> None:
        async with self._start_lock:
            await self._stop_process()

    async def _monitor(self) -> None:
        interval = max(5, min(15, settings.AI_IDLE_TIMEOUT_SECONDS // 4))
        while True:
            await asyncio.sleep(interval)
            if not settings.AI_MANAGED_SERVER:
                continue
            is_alive = await self.is_healthy() or (self.process and self.process.poll() is None)
            if not is_alive:
                continue
            async with self._state_lock:
                if self.last_used_at == 0.0:
                    self.last_used_at = time.monotonic()
                idle = time.monotonic() - self.last_used_at
                should_stop = self.active_requests == 0 and idle >= settings.AI_IDLE_TIMEOUT_SECONDS
            if should_stop:
                await self.stop()

    def start_monitor(self) -> None:
        if not self._monitor_task:
            self._monitor_task = asyncio.create_task(self._monitor())

    async def shutdown(self) -> None:
        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
            self._monitor_task = None
        await self.stop()

    async def status(self) -> dict:
        healthy = await self.is_healthy()
        idle_seconds = (
            max(0, int(time.monotonic() - self.last_used_at)) if self.last_used_at else None
        )
        return {
            "healthy": healthy,
            "managed": settings.AI_MANAGED_SERVER,
            "running": healthy or bool(self.process and self.process.poll() is None),
            "active_requests": self.active_requests,
            "idle_seconds": idle_seconds,
            "idle_timeout_seconds": settings.AI_IDLE_TIMEOUT_SECONDS,
            "model": settings.AI_MODEL,
            "model_exists": self.model_path().exists(),
            "mmproj_exists": bool(self.mmproj_path()),
            "executable": str(self.executable()) if self.executable() else None,
            "platform": "windows" if os.name == "nt" else "linux",
        }


model_runtime = ModelRuntime()
