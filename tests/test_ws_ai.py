from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest
import asyncio
from sqlalchemy import BigInteger, create_engine
from sqlalchemy.dialects.postgresql import ARRAY, CITEXT, JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.testclient import TestClient


from app.core.security import create_access_token
from app.db.base import Base
from app.main import app
from app.models import Role, User, UserStatus


@compiles(BigInteger, "sqlite")
def compile_biginteger_sqlite(type_, compiler, **kw):
    return "INTEGER"


@compiles(CITEXT, "sqlite")
def compile_citext_sqlite(type_, compiler, **kw):
    return "TEXT"


@compiles(JSONB, "sqlite")
def compile_jsonb_sqlite(type_, compiler, **kw):
    return "TEXT"


@compiles(ARRAY, "sqlite")
def compile_array_sqlite(type_, compiler, **kw):
    return "TEXT"



from sqlalchemy.pool import StaticPool

# Setup in-memory SQLite for hermetic tests
test_engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
Base.metadata.create_all(bind=test_engine)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


def test_nvidia_socket_routes_concurrent_replies_to_their_requests(auth_token_and_user, monkeypatch):
    from app.core.config import settings
    from app.services import ai, nvidia_agent
    token, _ = auth_token_and_user
    gate = None
    original = ai.run_agent_socket

    async def agent(db, user, message, memory, emit, **kwargs):
        nonlocal gate
        if gate is None:
            gate = asyncio.Event()
        if message == "Busca prendas":
            await gate.wait()
        return {"requires_llm": False, "direct_response": message, "action_items": [],
                "events_emitted": True, "response_meta": {"model_used": "test-model"}, "chat_context": {}}

    async def run(*args, **kwargs):
        await original(*args, **kwargs)
        if args[2] == "Consulta envíos":
            gate.set()

    monkeypatch.setattr(ai, "run_nvidia_agent", agent)
    monkeypatch.setattr(ai, "run_agent_socket", run)
    with TestClient(app).websocket_connect("/api/v1/ws/ai") as socket:
        socket.send_json({"type": "auth", "token": token})
        assert socket.receive_json()["concurrent"] is True
        socket.send_json({"type": "chat", "request_id": "m1", "message": "Busca prendas"})
        first = socket.receive_json()
        assert first["type"] == "task_started"
        socket.send_json({"type": "chat", "request_id": "m2", "message": "Consulta envíos", "session_id": first["session_id"]})
        socket.send_json({"type": "ping"})
        completed = []
        pong = False
        while len(completed) < 2:
            event = socket.receive_json()
            assert event["type"] != "error", event
            if event["type"] == "pong":
                pong = True
            if event["type"] == "done":
                completed.append(event["request_id"])
                assert event["session_id"] == first["session_id"]
        assert completed == ["m2", "m1"]
        assert pong



@pytest.fixture
def auth_token_and_user(monkeypatch):
    monkeypatch.setattr("app.db.session.SessionLocal", TestingSessionLocal)
    monkeypatch.setattr(
        "app.modules.inteligencia_artificial_y_asistencia_de_moda.cu18_consultar_al_asistente_inteligente_altair.SessionLocal",
        TestingSessionLocal,
    )

    with TestingSessionLocal() as db:
        user = db.query(User).filter(User.email == "admin@drapemind.com").first()
        if not user:
            user = User(
                id=1,
                email="admin@drapemind.com",
                nombre="Administrador",
                rol=Role.ADMIN,
                estado=UserStatus.ACTIVO,
                password_hash="hash",
            )
            db.add(user)
            db.commit()
            db.refresh(user)
        token, _ = create_access_token(user.id, user.rol.value)
        return token, user
