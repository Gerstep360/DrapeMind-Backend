from decimal import Decimal
from datetime import datetime, timezone
import uuid
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, BigInteger
from sqlalchemy.dialects.postgresql import JSONB, CITEXT, ARRAY
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

@compiles(BigInteger, 'sqlite')
def bigint(type_, compiler, **kw): return 'INTEGER'
@compiles(JSONB, 'sqlite')
def jsonb(type_, compiler, **kw): return 'JSON'
@compiles(CITEXT, 'sqlite')
def citext(type_, compiler, **kw): return 'TEXT'
@compiles(ARRAY, 'sqlite')
def array(type_, compiler, **kw): return 'JSON'


from app.db.base import Base
from app.db.tenant_session import TenantSession
from app.main import app
from app.api.deps import get_db, get_current_user
from app.models import Category, Product, ProductReview, Role, User, UserStatus, Order, OrderItem
from app.models.saas import Tenant


@pytest.fixture
def session_and_client():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TestingSession = sessionmaker(bind=engine, class_=TenantSession, autoflush=False, autocommit=False)
    db = TestingSession()

    # Seed Tenant
    t = Tenant(id=1, name="Test Boutique", slug="testboutique")
    db.add(t)
    db.commit()

    # Seed Users
    u1 = User(
        id=1,
        tenant_id=1,
        nombre="Carlos Mendoza",
        email="carlos@example.com",
        password_hash="fakehash",
        rol=Role.CLIENTE,
        estado=UserStatus.ACTIVO,
    )
    u2 = User(
        id=2,
        tenant_id=1,
        nombre="Elena Rios",
        email="elena@example.com",
        password_hash="fakehash",
        rol=Role.CLIENTE,
        estado=UserStatus.ACTIVO,
    )
    db.add_all([u1, u2])
    db.commit()

    # Seed Category
    cat = Category(id=1, tenant_id=1, nombre="Chaquetas", slug="chaquetas")
    db.add(cat)
    db.commit()

    # Seed Product
    prod = Product(
        id=10,
        tenant_id=1,
        categoria_id=1,
        nombre="Chaqueta Denim Vintage",
        descripcion="Chaqueta clásica de mezclilla",
        precio=Decimal("350.0"),
        activo=True,
    )
    db.add(prod)
    db.commit()

    client = TestClient(app)

    yield db, client, u1, u2, prod

    db.close()


def test_cu30_reviews_lifecycle(session_and_client):
    db, client, u1, u2, prod = session_and_client

    def override_get_db():
        try:
            yield db
        finally:
            pass

    def override_current_user():
        return u1

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_current_user

    try:
        # 1. Get reviews initially empty
        res = client.get("/api/v1/products/10/reviews")
        assert res.status_code == 200
        data = res.json()
        assert data["producto_id"] == 10
        assert data["promedio"] == 0.0
        assert data["total"] == 0
        assert data["resenas"] == []

        # 2. Post review without previous purchase (compra_verificada = False)
        payload = {
            "calificacion": 5,
            "titulo": "Hermosa prenda",
            "comentario": "Me encantó el estilo neubrutalista y la tela es muy cómoda.",
        }
        res = client.post("/api/v1/products/10/reviews", json=payload)
        assert res.status_code == 200
        rev1 = res.json()
        assert rev1["calificacion"] == 5
        assert rev1["titulo"] == "Hermosa prenda"
        assert rev1["compra_verificada"] is False
        assert rev1["usuario_nombre"] == "Carlos Mendoza"

        # 3. Simulate verified purchase by creating a paid order
        order = Order(
            id=100,
            tenant_id=1,
            usuario_id=u1.id,
            codigo_publico=uuid.uuid4(),
            estado="PAGADO",
            paid_at=datetime.now(timezone.utc),
            canal="WEB",
            tipo_entrega="DELIVERY",
            total=350.0,
            subtotal=350.0,
        )
        db.add(order)
        db.commit()
        item = OrderItem(
            id=200,
            tenant_id=1,
            pedido_id=100,
            producto_id=10,
            nombre_snapshot="Chaqueta Denim",
            sku_snapshot="CD-001",
            color_snapshot="Azul",
            talla_snapshot="M",
            cantidad=1,
            precio_unitario=350.0,
            subtotal=350.0,
        )
        db.add(item)
        db.commit()

        # Update review: should now be verified
        payload_update = {
            "calificacion": 4,
            "titulo": "Actualizado: muy buena",
            "comentario": "Probada después de comprarla, excelente corte.",
        }
        res = client.post("/api/v1/products/10/reviews", json=payload_update)
        assert res.status_code == 200
        rev1_updated = res.json()
        assert rev1_updated["calificacion"] == 4
        assert rev1_updated["compra_verificada"] is True

        # 4. User 2 posts a review
        app.dependency_overrides[get_current_user] = lambda: u2
        res2 = client.post(
            "/api/v1/products/10/reviews",
            json={
                "calificacion": 5,
                "titulo": "Impecable",
                "comentario": "Calidad premium, 100% recomendado.",
            },
        )
        assert res2.status_code == 200

        # 5. Check aggregated stats: average should be (4 + 5) / 2 = 4.5
        res_all = client.get("/api/v1/products/10/reviews")
        assert res_all.status_code == 200
        stats = res_all.json()
        assert stats["total"] == 2
        assert stats["promedio"] == 4.5
        assert stats["distribucion"]["4"] == 1
        assert stats["distribucion"]["5"] == 1

        # 6. Delete review for User 2
        res_del = client.delete("/api/v1/products/10/reviews")
        assert res_del.status_code == 200

        # Stats after delete: 1 review remaining, average 4.0
        res_after = client.get("/api/v1/products/10/reviews")
        assert res_after.json()["total"] == 1
        assert res_after.json()["promedio"] == 4.0

    finally:
        app.dependency_overrides.clear()
