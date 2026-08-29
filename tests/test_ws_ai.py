from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest
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


def test_ws_ai_full_flow(auth_token_and_user, monkeypatch):
    token, user = auth_token_and_user

    async def fake_completion(*args, **kwargs):
        if kwargs.get("stream"):
            mock_client = MagicMock()
            mock_client.aclose = AsyncMock()
            mock_resp = MagicMock()
            mock_resp.status_code = 200

            async def fake_lines():
                yield 'data: {"choices": [{"delta": {"content": "Respuesta asistida Altair"}}]}'
                yield "data: [DONE]"

            mock_resp.aiter_lines = fake_lines
            mock_resp.raise_for_status = MagicMock()

            class FakeStreamCtx:
                async def __aenter__(self):
                    return mock_resp

                async def __aexit__(self, exc_type, exc_val, exc_tb):
                    pass

            mock_client.stream = MagicMock(return_value=FakeStreamCtx())
            return mock_client, {}, {}
        return {
            "choices": [
                {
                    "message": {
                        "content": '{"type": "finish", "answer": "Respuesta asistida Altair", "title": "Asesoría", "presentation": "text"}'
                    }
                }
            ]
        }

    monkeypatch.setattr("app.services.ai._completion", fake_completion)
    monkeypatch.setattr("app.services.ai.model_runtime.is_healthy", AsyncMock(return_value=True))

    @asynccontextmanager
    async def fake_lease():
        yield

    monkeypatch.setattr("app.services.ai.model_runtime.lease", fake_lease)

    client = TestClient(app)

    with client.websocket_connect("/api/v1/ws/ai") as ws:
        # 1. Auth
        ws.send_json({"type": "auth", "token": token})
        connected = ws.receive_json()
        assert connected["type"] == "connected"

        # 2. Ping
        ws.send_json({"type": "ping"})
        pong = ws.receive_json()
        assert pong["type"] == "pong"

        # 3. Test multiple prompts with stale session_id (e.g. 999999)
        test_prompts = [
            "Hola Altair",
            "Mira mi carrito y dime que puedo quitar o que puedo combinar en mi eleccion",
            "Arma un outfit elegante para una cena de gala con presupuesto de 800 Bs",
            "Busco camisas de lino blanco en talla M",
            "Cobré mi sueldo y quiero comprar algo de calidad",
            "Muéstrame las piezas más exclusivas del showroom",
        ]

        for prompt in test_prompts:
            ws.send_json({
                "type": "chat",
                "message": prompt,
                "session_id": 999999,
            })

            received_events = []
            while True:
                evt = ws.receive_json()
                evt_type = evt.get("type")
                received_events.append(evt_type)
                if evt_type == "error":
                    pytest.fail(f"Error recibido en prompt '{prompt}': {evt.get('message')}")
                if evt_type == "done":
                    assert "session_id" in evt
                    assert evt["session_id"] is not None
                    break

            assert "done" in received_events

