import asyncio
import logging
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
logger = logging.getLogger("drapemind.ai.runtime")


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

    def _read_recent_logs(self, max_lines: int = 15) -> str:
        log_file = BACKEND_DIR / "logs" / "llama-server.log"
        if not log_file.exists():
            return ""
        try:
            with log_file.open("r", encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()
                return "".join(lines[-max_lines:]).strip()
        except Exception:
            return ""

    async def is_healthy(self) -> bool:
        base = settings.AI_BASE_URL.rstrip("/")
        root_url = base[:-3] if base.endswith("/v1") else base
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                try:
                    resp = await client.get(f"{root_url}/health")
                    if resp.status_code == 200:
                        return True
                except httpx.HTTPError:
                    pass
                response = await client.get(f"{base}/models")
                return response.status_code == 200
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

        # Ensure GPU layers is an integer string: llama.cpp CLI rejects "auto"
        ngl = str(settings.AI_GPU_LAYERS).strip()
        ngl_val = ngl if (ngl.isdigit() or (ngl.startswith("-") and ngl[1:].isdigit())) else "0"

        # Context size: limit to 3072 on CPU to keep memory footprint strictly under 2.8 GB
        ctx_size = min(int(settings.AI_CONTEXT_SIZE or 4096), 3072)
        parallel_slots = max(1, min(int(settings.AI_PARALLEL_SLOTS or 1), 1))

        command = [
            str(executable),
            "--model", str(model),
            "--alias", settings.AI_MODEL,
            "--host", settings.AI_SERVER_HOST,
            "--port", str(settings.AI_SERVER_PORT),
            "--ctx-size", str(ctx_size),
            "--parallel", str(parallel_slots),
            "-ngl", ngl_val,
            "--jinja",
        ]
        # llama-server is an OpenAI-compatible text/reasoning server; --mmproj is not a valid CLI argument for llama-server

        threads = settings.AI_THREADS
        if threads <= 0 and os.name != "nt":
            # Cap at 2 threads to protect the 8 GB VPS and other concurrent services
            threads = min(os.cpu_count() or 2, 2)
        if threads > 0:
            command.extend(["--threads", str(threads)])

        if settings.AI_SERVER_EXTRA_ARGS:
            command.extend(shlex.split(settings.AI_SERVER_EXTRA_ARGS, posix=os.name != "nt"))
        return command

    def _cleanup_stale_processes(self) -> None:
        """Kills any orphaned llama-server process on the system."""
        if os.name == "nt":
            try:
                subprocess.run(
                    ["taskkill", "/F", "/IM", "llama-server.exe"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except Exception:
                pass
        else:
            try:
                subprocess.run(
                    ["pkill", "-9", "-f", "llama-server"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except Exception:
                pass

    async def ensure_started(self) -> None:
        self.start_monitor()
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
            # Clean up any stale process binding port before starting
            self._cleanup_stale_processes()
            command = self.command()
            log_dir = BACKEND_DIR / "logs"
            log_dir.mkdir(exist_ok=True)
            self._log_handle = (log_dir / "llama-server.log").open("ab")
            creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
            logger.info("Iniciando proceso llama-server (puerto %s)...", settings.AI_SERVER_PORT)

            # Configure environment for GGML dynamic backend loading
            runtime_env = os.environ.copy()
            exec_path = self.executable()
            exec_dir = exec_path.parent if exec_path else Path("/usr/local/bin")
            candidate_dirs = [
                exec_dir,
                Path("/usr/local/bin"),
                Path("/usr/local/lib"),
                Path("/opt/llama.cpp"),
                BACKEND_DIR / "vendor" / "llama.cpp",
            ]

            backend_dir = exec_dir
            for cdir in candidate_dirs:
                if cdir.is_dir() and (
                    (cdir / "libggml-cpu-x64.so").exists()
                    or list(cdir.glob("libggml-cpu*.so"))
                ):
                    backend_dir = cdir
                    break

            # If libraries are in /usr/local/lib but missing in exec_dir, copy them next to llama-server
            if backend_dir != exec_dir and exec_dir.is_dir():
                try:
                    for lib_file in backend_dir.glob("libggml*"):
                        dest = exec_dir / lib_file.name
                        if not dest.exists():
                            shutil.copy2(lib_file, dest)
                    for lib_file in backend_dir.glob("libllama*"):
                        dest = exec_dir / lib_file.name
                        if not dest.exists():
                            shutil.copy2(lib_file, dest)
                except Exception:
                    pass

            lib_paths = [
                str(backend_dir),
                str(exec_dir),
                "/usr/local/bin",
                "/usr/local/lib",
                "/opt/llama.cpp",
                str(BACKEND_DIR / "vendor" / "llama.cpp"),
            ]
            existing_ld = runtime_env.get("LD_LIBRARY_PATH", "")
            runtime_env["LD_LIBRARY_PATH"] = ":".join(
                p for p in [existing_ld] + lib_paths if p
            ).strip(":")
            runtime_env["GGML_BACKEND_PATH"] = str(backend_dir)

            self.process = subprocess.Popen(
                command,
                cwd=str(BACKEND_DIR),
                env=runtime_env,
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
                exit_code = self.process.returncode
                log_tail = self._read_recent_logs(15)
                await self._stop_process()
                detail = f" (Código de salida {exit_code}):\n{log_tail}" if log_tail else f" (Código {exit_code})."
                raise ModelRuntimeError(
                    f"llama-server terminó durante el arranque{detail}"
                )
            if await self.is_healthy():
                logger.info("llama-server listo y saludable en puerto %s", settings.AI_SERVER_PORT)
                return
            await asyncio.sleep(1.0)
        log_tail = self._read_recent_logs(15)
        await self._stop_process()
        detail = f":\n{log_tail}" if log_tail else "."
        raise ModelRuntimeError(
            f"Gemma no estuvo listo antes del timeout ({settings.AI_STARTUP_TIMEOUT_SECONDS}s){detail}"
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
                await asyncio.to_thread(process.wait, 5)
            except subprocess.TimeoutExpired:
                process.kill()
                await asyncio.to_thread(process.wait, 5)
        self._cleanup_stale_processes()
        if self._log_handle:
            try:
                self._log_handle.close()
            except Exception:
                pass
            self._log_handle = None
        logger.info("llama-server detenido exitosamente; memoria RAM liberada.")

    async def stop(self) -> None:
        async with self._start_lock:
            await self._stop_process()

    async def _monitor(self) -> None:
        interval = max(5, min(15, settings.AI_IDLE_TIMEOUT_SECONDS // 4))
        while True:
            try:
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
                    logger.info(
                        "AI Idle timeout alcanzado (%ds inactivo >= %ds). Deteniendo llama-server para liberar memoria...",
                        int(idle),
                        settings.AI_IDLE_TIMEOUT_SECONDS,
                    )
                    await self.stop()
            except asyncio.CancelledError:
                break
            except Exception as err:
                logger.error("Error en monitor de inactividad de IA: %s", err)

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
