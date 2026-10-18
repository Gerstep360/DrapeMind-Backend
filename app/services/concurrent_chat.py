"""Bounded connection-scoped tasks. Each turn owns its SQLAlchemy session."""

import asyncio
from dataclasses import dataclass
import logging
from uuid import uuid4

from fastapi import HTTPException, WebSocketDisconnect

from app.models import User, UserStatus
from app.services.ai_errors import AIProviderError

logger = logging.getLogger("drapemind.chat.tasks")


@dataclass
class ChatJob:
    task_id: str
    request_id: str
    version: int
    session_id: int
    message: str
    task: asyncio.Task | None = None
    cancelled: bool = False


class ConnectionTasks:
    def __init__(self, send, limit=3):
        self.send = send
        self.limit = limit
        self.jobs: dict[str, ChatJob] = {}
        self.version = 0

    async def emit(self, job, event):
        if not job.cancelled:
            await self.send(
                {
                    **event,
                    "request_id": job.request_id,
                    "task_id": job.task_id,
                    "request_version": job.version,
                    "session_id": job.session_id,
                }
            )

    async def cancel(self, task_id):
        job = self.jobs.get(task_id)
        if not job or job.cancelled:
            return {
                "cancelled": False,
                "message": "La tarea ya terminó o no pertenece a esta conexión.",
            }
        job.cancelled = True
        if job.task:
            job.task.cancel()
            await asyncio.gather(job.task, return_exceptions=True)
        await self.send(
            {
                "type": "task_cancelled",
                "task_id": job.task_id,
                "request_id": job.request_id,
                "request_version": job.version,
                "session_id": job.session_id,
            }
        )
        return {"cancelled": True}

    async def submit(self, request_id, session_id, message, operation):
        if len(self.jobs) >= self.limit:
            raise HTTPException(
                429, "Hay tres consultas en curso. Espera un resultado o cancela una."
            )
        if any(job.request_id == request_id for job in self.jobs.values()):
            raise HTTPException(409, "Este mensaje ya está en curso.")
        self.version += 1
        job = ChatJob(str(uuid4()), request_id, self.version, session_id, message)
        self.jobs[job.task_id] = job
        await self.emit(job, {"type": "task_started"})

        async def run():
            try:
                pending = [
                    {"task_id": other.task_id, "message": other.message}
                    for other in self.jobs.values()
                    if other is not job and other.session_id == session_id
                ]

                async def cancel_other(task_id):
                    target = self.jobs.get(task_id)
                    if not target or target is job or target.session_id != session_id:
                        return {
                            "cancelled": False,
                            "message": "No puedes cancelar esa tarea.",
                        }
                    return await self.cancel(task_id)

                await operation(
                    lambda event: self.emit(job, event),
                    {"pending": pending, "cancel": cancel_other},
                )
                await self.emit(job, {"type": "task_completed"})
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning(
                    "Chat task failed task_id=%s error_type=%s",
                    job.task_id,
                    type(exc).__name__,
                )
                detail = (
                    exc.detail
                    if isinstance(exc, HTTPException)
                    else str(exc)
                    if isinstance(exc, AIProviderError)
                    else "Altair no pudo completar la consulta. Puedes reintentarlo."
                )
                await self.emit(
                    job, {"type": "error", "code": "AI_UNAVAILABLE", "message": detail}
                )
                await self.emit(job, {"type": "task_failed"})
            finally:
                self.jobs.pop(job.task_id, None)

        job.task = asyncio.create_task(run())
        return job

    async def close(self):
        tasks = []
        for job in list(self.jobs.values()):
            job.cancelled = True
            if job.task:
                job.task.cancel()
                tasks.append(job.task)
        await asyncio.gather(*tasks, return_exceptions=True)
        self.jobs.clear()


async def serve_nvidia_socket(socket, user_id, session_factory):
    from app.services.ai import get_ai_session, run_agent_socket, sanitize_for_json

    lock = asyncio.Lock()

    async def send(event):
        async with lock:
            await socket.send_json(sanitize_for_json(event))

    with session_factory() as db:
        user = db.get(User, user_id)
        if not user or user.estado != UserStatus.ACTIVO:
            await socket.close(code=4401, reason="Usuario inactivo")
            return
    manager = ConnectionTasks(send)
    default_session = None
    await send(
        {
            "type": "connected",
            "channel": "ai",
            "concurrent": True,
            "max_tasks": manager.limit,
        }
    )
    try:
        while True:
            data = await socket.receive_json()
            if not isinstance(data, dict):
                await send(
                    {"type": "error", "message": "El evento debe ser un objeto JSON."}
                )
                continue
            if data.get("type") == "ping":
                await send({"type": "pong"})
                continue
            if data.get("type") == "cancel":
                await manager.cancel(str(data.get("task_id") or ""))
                continue
            request_id = str(data.get("request_id") or uuid4())[:100]
            message = data.get("message")
            if (
                data.get("type") != "chat"
                or not isinstance(message, str)
                or not 2 <= len(message.strip()) <= 2000
            ):
                await send(
                    {
                        "type": "error",
                        "request_id": request_id,
                        "message": "El mensaje debe tener 2 a 2000 caracteres.",
                    }
                )
                continue
            try:
                with session_factory() as db:
                    session = get_ai_session(
                        db, user_id, data.get("session_id") or default_session
                    )
                    session_id = session.id
                    db.commit()
                default_session = session_id

                async def operation(
                    emit, context, message=message, session_id=session_id
                ):
                    with session_factory() as turn_db:
                        turn_user = turn_db.get(User, user_id)
                        if not turn_user or turn_user.estado != UserStatus.ACTIVO:
                            raise HTTPException(401, "Usuario inactivo")
                        from app.db.tenant_session import TenantSession
                        if isinstance(turn_db,TenantSession):
                            from app.services.saas import require_active_subscription
                            require_active_subscription(turn_db,turn_user.tenant_id)
                        await run_agent_socket(
                            turn_db,
                            turn_user,
                            message,
                            session_id,
                            emit,
                            task_context=context,
                        )

                await manager.submit(request_id, session_id, message, operation)
            except (HTTPException, ValueError, TypeError) as exc:
                detail = (
                    exc.detail
                    if isinstance(exc, HTTPException)
                    else "Conversación inválida."
                )
                await send(
                    {"type": "error", "request_id": request_id, "message": detail}
                )
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        await manager.close()
