import pytest
import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.services.ai_skills.skill_registry import skill_registry
from app.services.ai_skills.catalog_skill import CatalogSkill
from app.services.ai_skills.general_chat_skill import GeneralChatSkill
from app.services.ai_skills.outfit_skill import OutfitSkill
from app.services import ai as ai_service
from app.services.ai_agent import run_gemma_tool_agent


@pytest.mark.parametrize(
    "query,expected_skill",
    [
        ("hola", "general_chat_skill"),
        ("buenos dias", "general_chat_skill"),
        ("quien eres y que haces?", "general_chat_skill"),
        ("muchas gracias!", "general_chat_skill"),
        ("quiero comprar una camisa de lino", "catalog_skill"),
        ("tienes pantalones negros en stock?", "catalog_skill"),
        ("muestrame opciones de ropa barata", "catalog_skill"),
        ("que tengo en mi carrito?", "cart_skill"),
        ("revisa mi carrito de compras", "cart_skill"),
        ("analizar mi eleccion en el carrito", "cart_skill"),
        ("califica mi carrito", "cart_skill"),
        ("mira mi carrito y dime que puedo quitar o que puedo combinar en mi eleccion", "cart_skill"),
        ("como se ve mi eleccion en el carrito", "cart_skill"),
        ("donde esta mi pedido #5?", "orders_skill"),
        ("cuantos pedidos tengo en mi cuenta?", "orders_skill"),
        ("tengo algun pedido pendiente?", "orders_skill"),
        ("estado de mis pedidos", "orders_skill"),
        ("ver mis compras", "orders_skill"),
        ("quiero otro pedido, buscame ropa tengo 800bs de presupuesto", "catalog_skill"),
        ("arma un outfit para una cena elegante", "outfit_skill"),
        ("como combinar una chaqueta de cuero?", "outfit_skill"),
    ],
)
def test_skill_resolution(query: str, expected_skill: str):
    skill = skill_registry.resolve(query)
    assert skill.name == expected_skill, f"Query '{query}' resolved to {skill.name}, expected {expected_skill}"


def test_general_chat_is_direct_and_text_only():
    result = GeneralChatSkill().execute(
        None,
        SimpleNamespace(nombre="Ana"),
        "hola",
        {},
    )
    assert result["requires_llm"] is False
    assert result["presentation_mode"] == "text"
    assert len(result["direct_response"]) < 240


def test_catalog_search_returns_instant_action_cards(monkeypatch):
    product = {
        "id": 8,
        "nombre": "Camisa de lino",
        "precio": 240,
        "calidad_nivel": 4,
        "imagenes": ["/media/camisa.webp"],
    }
    monkeypatch.setattr(
        "app.services.ai_skills.catalog_skill.execute_tool",
        lambda *_args, **_kwargs: [product],
    )
    monkeypatch.setattr(
        "app.services.ai_skills.catalog_skill.get_product_detail",
        lambda *_args, **_kwargs: {
            "variantes": [
                {
                    "id": 21,
                    "activo": True,
                    "stock_disponible": 3,
                    "color": "Beige",
                    "talla": "M",
                    "sku": "CAM-21",
                    "imagen": None,
                }
            ]
        },
    )

    result = CatalogSkill().execute(
        None,
        SimpleNamespace(id=1),
        "muestrame camisas de lino",
        {},
    )

    assert result["requires_llm"] is True
    assert result["presentation_mode"] == "mixed"
    assert result["action_items"][0]["accion"] == "AGREGAR"
    assert result["action_items"][0]["variante_id"] == 21


def test_greeting_is_decided_by_gemma_without_repeating_welcome(monkeypatch):
    events = []
    session = SimpleNamespace(id=9, resumen_contexto=None)
    interaction = SimpleNamespace(id=77)
    async def fake_agent(*_args, **_kwargs):
        return {
            "tool_name": None,
            "tool_args": {},
            "tool_result": None,
            "action_items": [],
            "requires_llm": False,
            "direct_response": "¿Qué te gustaría explorar hoy?",
            "presentation_mode": "text",
            "response_title": None,
        }

    @asynccontextmanager
    async def allowed_lease():
        yield

    async def healthy():
        return True

    monkeypatch.setattr(ai_service, "get_ai_session", lambda *_args: session)
    monkeypatch.setattr(ai_service, "_save_interaction", lambda *_args, **_kwargs: interaction)
    monkeypatch.setattr(ai_service, "run_gemma_tool_agent", fake_agent)
    monkeypatch.setattr(ai_service.model_runtime, "lease", allowed_lease)
    monkeypatch.setattr(ai_service.model_runtime, "is_healthy", healthy)

    async def send(event):
        events.append(event)

    asyncio.run(
        ai_service.run_agent_socket(
            MagicMock(),
            SimpleNamespace(id=1, nombre="Ana"),
            "hola",
            None,
            send,
        )
    )

    tokens = [e["content"] for e in events if e["type"] == "token"]
    assert "".join(tokens) == "¿Qué te gustaría explorar hoy?"
    assert "hola" not in "".join(tokens).lower()
    done = next(event for event in events if event["type"] == "done")
    assert done["duration_ms"] >= 0


def test_outfit_budget_is_calculated_by_fastapi(monkeypatch):
    captured_args = {}

    def fake_tool(_name, args, _context):
        captured_args.update(args)
        return {
            "tops_sugeridos": [
                {"id": 1, "variante_id": 11, "nombre": "Top", "precio": 250}
            ],
            "inferiores_sugeridos": [
                {"id": 2, "variante_id": 22, "nombre": "Pantalon", "precio": 260}
            ],
            "calzado_sugerido": [
                {"id": 3, "variante_id": 33, "nombre": "Zapato", "precio": 310}
            ],
            "complementos_abrigos": [
                {"id": 4, "variante_id": 44, "nombre": "Cinturon", "precio": 90}
            ],
        }

    monkeypatch.setattr(
        "app.services.ai_skills.outfit_skill.execute_tool",
        fake_tool,
    )
    result = OutfitSkill().execute(
        None,
        SimpleNamespace(id=1),
        "arma un outfit para cena con presupuesto de Bs 700",
        {},
    )

    assert captured_args["max_budget"] == 700
    assert sum(item["precio"] for item in result["action_items"]) <= 700
    assert result["tool_result"]["presupuesto_cumplido"] is True


def test_outfit_preserves_sizes_and_reports_missing_shoes(monkeypatch):
    captured_args = {}

    def fake_tool(_name, args, _context):
        captured_args.update(args)
        return {
            "tops_sugeridos": [
                {
                    "id": 1,
                    "variante_id": 11,
                    "nombre": "Polera",
                    "precio": 180,
                    "talla": "M",
                }
            ],
            "inferiores_sugeridos": [
                {
                    "id": 2,
                    "variante_id": 22,
                    "nombre": "Pantalon Palazzo",
                    "precio": 240,
                    "talla": "S",
                }
            ],
            "calzado_sugerido": [],
            "complementos_abrigos": [],
            "restricciones_sin_stock": ["No hay calzado en talla 45"],
        }

    monkeypatch.setattr(
        "app.services.ai_skills.outfit_skill.execute_tool",
        fake_tool,
    )
    result = OutfitSkill().execute(
        None,
        SimpleNamespace(id=1),
        (
            "un outfit, mi talla es M en polera, en pantalon lo quiero ancho, "
            "zapatos soy 45 y cintura 90 cm"
        ),
        {},
    )

    assert captured_args["top_size"] == "M"
    assert captured_args["shoe_size"] == "45"
    assert captured_args["bottom_fit"] == "ancho"
    assert captured_args["measurements"] == {"cintura": 90.0}
    assert all(item["talla"] != "39" for item in result["action_items"])
    assert "talla 45" in result["notices"][0]["message"]


def test_cart_skill_handles_scale_and_balance_critique(monkeypatch):
    from app.services.ai_skills.cart_skill import CartSkill

    skill = CartSkill()
    msg = "Piensa si mi lista que puse en mi carrito esta bien equilibrada, quiero que lo analices y me digas en una escala del 1 al 10 qué tan buena esta"
    assert skill.can_handle(msg, {}) is True

    fake_cart = {
        "items": [
            {"id": 1, "producto_id": 10, "variante_id": 101, "nombre": "Polera Basica", "color": "Negro", "talla": "L", "cantidad": 2, "precio_unitario": 120, "subtotal": 240},
            {"id": 2, "producto_id": 20, "variante_id": 201, "nombre": "Pantalon Sastrero", "color": "Marfil", "talla": "M", "cantidad": 1, "precio_unitario": 319, "subtotal": 319},
        ],
        "subtotal": 559.0,
    }

    monkeypatch.setattr(
        "app.services.ai_skills.cart_skill.execute_tool",
        lambda name, args, ctx: fake_cart if name == "get_my_cart" else [],
    )

    res = skill.execute(None, SimpleNamespace(id=1, nombre="Carlos"), msg, {})
    assert "calificación del perchero" in res["fallback_response"].lower()
    assert "10" in res["fallback_response"]
    assert "Carlos" in res["fallback_response"]
    assert len(res["action_items"]) == 2


def test_optimize_outfit_skill_balance_and_cpw(monkeypatch):
    from app.services.ai_skills.optimize_outfit_skill import OptimizeOutfitSkill

    skill = OptimizeOutfitSkill()
    msg = "optimizar outfit para comprar ropa de calidad que dure y evitar cosas baratas"
    assert skill.can_handle(msg, {}) is True

    high_q = [{"id": 1, "nombre": "Blazer Sastrero Lana", "precio": 450, "calidad_nivel": 5, "material": "Lana Pura"}]
    low_q = [{"id": 2, "nombre": "Polera Algodon Pima", "precio": 140, "calidad_nivel": 3, "material": "Algodon"}]

    monkeypatch.setattr(
        "app.services.ai_skills.optimize_outfit_skill.execute_tool",
        lambda name, args, ctx: high_q if args.get("calidad_min") == 4 else low_q,
    )
    monkeypatch.setattr(
        "app.services.ai_skills.optimize_outfit_skill.get_product_detail",
        lambda db, pid: {"variantes": [{"id": pid * 10, "activo": True, "stock_disponible": 5, "color": "Azul", "talla": "M"}]},
    )

    res = skill.execute(None, SimpleNamespace(id=1, nombre="Carlos"), msg, {})
    assert "inversión" in res["fallback_response"].lower()
    assert "Q" in res["fallback_response"]
    assert len(res["action_items"]) >= 1


def test_composite_skill_orchestration(monkeypatch):
    from app.services.ai_skills.skill_registry import skill_registry
    from app.services.ai_skills.composite_skill import CompositeSkill

    # Solicitud que involucra tanto revisar carrito como armar outfit
    msg = "revisa mi carrito y arma un outfit para cena con presupuesto de 500 bs"
    resolved = skill_registry.resolve(msg, {})
    assert isinstance(resolved, CompositeSkill)
    assert len(resolved.active_skills) >= 2

    fake_cart = {"items": [], "subtotal": 0.0}
    fake_outfit = {
        "tops_sugeridos": [{"id": 1, "variante_id": 11, "nombre": "Polera", "precio": 120, "talla": "M"}],
        "inferiores_sugeridos": [],
        "calzado_sugerido": [],
        "complementos_abrigos": [],
    }

    monkeypatch.setattr(
        "app.services.ai_skills.cart_skill.execute_tool",
        lambda name, args, ctx: fake_cart,
    )
    monkeypatch.setattr(
        "app.services.ai_skills.outfit_skill.execute_tool",
        lambda name, args, ctx: fake_outfit,
    )

    res = resolved.execute(None, SimpleNamespace(id=1, nombre="Carlos"), msg, {})
    assert res["requires_llm"] is True
    assert len(res["composite_sub_tools"]) >= 2
    assert "Carlos" in res["fallback_response"]


def test_agent_socket_with_tools_runs_without_missing_imports(monkeypatch):
    events = []
    session = SimpleNamespace(id=99, resumen_contexto=None)
    interaction = SimpleNamespace(id=88)

    async def fake_agent(*args, **kwargs):
        return {
            "tool_name": "gemma_agent",
            "tool_args": {"steps": 1},
            "tool_result": {},
            "composite_sub_tools": [
                {
                    "name": "recommend_outfit",
                    "args": {"occasion": "cena"},
                    "result": {"seleccion": []},
                    "reason": "Diseñar un outfit",
                }
            ],
            "action_items": [],
            "requires_llm": False,
            "direct_response": "No encontré una combinación completa.",
            "presentation_mode": "text",
            "response_title": "Resultado",
        }

    @asynccontextmanager
    async def allowed_lease():
        yield

    async def healthy():
        return True

    monkeypatch.setattr(ai_service, "get_ai_session", lambda *_args: session)
    monkeypatch.setattr(ai_service, "_save_interaction", lambda *_args, **_kwargs: interaction)
    monkeypatch.setattr(ai_service, "run_gemma_tool_agent", fake_agent)
    monkeypatch.setattr(ai_service.model_runtime, "lease", allowed_lease)
    monkeypatch.setattr(ai_service.model_runtime, "is_healthy", healthy)

    async def send(event):
        events.append(event)

    asyncio.run(
        ai_service.run_agent_socket(
            MagicMock(),
            SimpleNamespace(id=1, nombre="German"),
            "arma un outfit para cena",
            None,
            send,
        )
    )

    thought_events = [e for e in events if e["type"] == "thought"]
    assert len(thought_events) >= 1
    done = next(e for e in events if e["type"] == "done")
    assert done["duration_ms"] >= 0


def test_gemma_agent_executes_the_allowed_tool_selected_by_the_model(monkeypatch):
    live_events = []
    decisions = iter(
        [
            {
                "choices": [
                    {
                        "message": {
                            "content": (
                                '{"type":"tool","tool":"get_my_reservations",'
                                '"arguments":{},"reason":"Consultar reservas activas"}'
                            )
                        }
                    }
                ]
            },
            {
                "choices": [
                    {
                        "message": {
                            "content": (
                                '{"type":"finish","answer":"Tienes una reserva activa.",'
                                '"title":"Reservas verificadas","presentation":"mixed"}'
                            )
                        }
                    }
                ]
            },
        ]
    )

    async def fake_complete(*_args, **_kwargs):
        return next(decisions)

    async def emit(event):
        live_events.append(event)

    monkeypatch.setattr(
        "app.services.ai_agent.execute_tool",
        lambda name, *_args, **_kwargs: [
            {"id": 14, "status": "ACTIVA", "expires_at": "2026-09-01T18:00:00"}
        ]
        if name == "get_my_reservations"
        else [],
    )
    monkeypatch.setattr(
        "app.services.ai_agent._cards_from_tool",
        lambda *_args, **_kwargs: [
            {
                "id": 14,
                "nombre": "Reserva #14",
                "precio": 0,
                "accion": "VER_RESERVA",
            }
        ],
    )

    result = asyncio.run(
        run_gemma_tool_agent(
            MagicMock(),
            SimpleNamespace(id=1),
            "¿Cuándo vence mi próxima reserva activa?",
            {},
            fake_complete,
            emit=emit,
        )
    )

    assert result["composite_sub_tools"][0]["name"] == "get_my_reservations"
    assert len(result["action_items"]) == 1
    assert result["action_items"][0]["nombre"] == "Reserva #14"
    assert any(event["type"] == "thought" for event in live_events)
    assert any(event["type"] == "tool_start" for event in live_events)
    assert any(event["type"] == "tool_result" for event in live_events)
    assert result["events_emitted"] is True
