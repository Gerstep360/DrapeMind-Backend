"""Real NVIDIA + PostgreSQL preference/form/savings checks; disposable account only."""

import asyncio
import json
import secrets
from decimal import Decimal
from uuid import uuid4
import httpx
import websockets
from sqlalchemy import select, delete
from app.db.session import SessionLocal
from app.models import Product, ProductVariant, Category, User, UserStyleProfile, City
from app.services.personal_shopping import _group
from scripts.diagnostics.check_dynamic_ui import ask


async def main():
    with SessionLocal() as db:
        rows = list(
            db.execute(
                select(Product, ProductVariant, Category)
                .join(ProductVariant, ProductVariant.producto_id == Product.id)
                .join(Category, Category.id == Product.categoria_id)
                .where(
                    Product.activo.is_(True),
                    ProductVariant.activo.is_(True),
                    ProductVariant.stock_total > ProductVariant.stock_reservado,
                )
                .order_by(Product.id, ProductVariant.id)
            )
        )
        candidates = [
            (p, v, c) for p, v, c in rows if _group(c.nombre, p.nombre) == "upper"
        ]
        assert candidates, "Se necesita stock real de prendas superiores."
        p, v, category = candidates[0]
        alternate = next(
            (w for q, w, c in candidates if q.id == p.id and w.talla != v.talla), None
        )
        profile_size, product_id = v.talla, p.id
        budget = max(Decimal("500"), p.precio * 3)
        gender = p.genero_objetivo.value
        catalog = {q.id: Decimal(q.precio) for q, _, _ in rows}
        live_variants = {w.id: w.talla for _, w, _ in rows}
        city = db.scalar(
            select(City.nombre).where(City.activo.is_(True)).order_by(City.id).limit(1)
        )
        grouped = {}
        for q, w, _ in rows:
            key = (q.categoria_id, w.talla, w.color, q.genero_objetivo)
            grouped.setdefault(key, []).append((q, w))
        savings_origin = next(
            (
                max(group, key=lambda r: r[0].precio)[1].id
                for group in grouped.values()
                if len({q.precio for q, _ in group}) > 1
            ),
            v.id,
        )
    user_id = None
    async with httpx.AsyncClient(
        base_url="http://127.0.0.1:8000/api/v1", timeout=30
    ) as client:
        try:
            credentials = {
                "email": f"qa-preferences-{uuid4().hex}@example.com",
                "password": secrets.token_urlsafe(24),
            }
            response = await client.post(
                "/auth/register", json={**credentials, "nombre": "QA preferencias"}
            )
            response.raise_for_status()
            user_id = response.json()["id"]
            with SessionLocal() as db:
                db.add(
                    UserStyleProfile(
                        usuario_id=user_id,
                        genero=gender,
                        talla_superior=profile_size,
                        talla_inferior=profile_size,
                        talla_calzado=profile_size,
                        colores_favoritos=[v.color],
                        estilos_preferidos=["casual"],
                        presupuesto_habitual=budget,
                        completado=True,
                    )
                )
                db.commit()
            response = await client.post("/auth/login", json=credentials)
            response.raise_for_status()
            token = response.json()["access_token"]
            client.headers["Authorization"] = "Bearer " + token
            setup = await client.get("/ai/shopping-setup", params={"goal": "budget"})
            setup.raise_for_status()
            assert setup.json()["type"] == "shopping_question"
            assert next(
                f["value"] for f in setup.json()["fields"] if f["key"] == "budget"
            ) == str(budget.quantize(Decimal(".01")))
            print(
                "Preparación sin NVIDIA: presupuesto y tallas precargados del perfil.",
                flush=True,
            )
            async with websockets.connect(
                "ws://127.0.0.1:8000/api/v1/ws/ai", origin="http://localhost:4200"
            ) as socket:
                await socket.send(json.dumps({"type": "auth", "token": token}))
                assert json.loads(await socket.recv())["type"] == "connected"
                response = await ask(
                    socket,
                    "Busca camisas para mí usando mis tallas y preferencias guardadas. Muéstrame hasta dos prendas y las razones.",
                    "profile",
                )
                assert (
                    "discover_for_me" in response["tools"]
                    or "search_products" in response["tools"]
                )
                assert response["action_items"] and all(
                    c["talla"] == profile_size for c in response["action_items"]
                )
                assert all(
                    Decimal(str(c["precio"])) == catalog[c["id"]]
                    for c in response["action_items"]
                )
                session = response["session_id"]
                print(
                    "NVIDIA real: consulta personal respeta talla guardada y precios de PostgreSQL.",
                    flush=True,
                )
                if alternate:
                    response = await ask(
                        socket,
                        f"Esta vez quiero la prenda ID {product_id}, pero talla {alternate.talla}. Esa talla tiene prioridad sobre mi perfil. Busca esa talla exacta.",
                        "override",
                        session,
                    )
                    shown = response["action_items"] or response.get(
                        "verified_products", []
                    )
                    print(
                        "Cambio de talla: herramientas=",
                        response["tools"],
                        "tallas=",
                        [c.get("talla") for c in shown],
                        flush=True,
                    )
                    assert shown and all(c["talla"] == alternate.talla for c in shown)
                    print(
                        "NVIDIA real: talla explícita prevalece sobre el perfil.",
                        flush=True,
                    )
                response = await ask(
                    socket,
                    f"Calcula cómo llevar más prendas distintas dentro de {budget} Bs con mis tallas guardadas, sin cambiar mi carrito.",
                    "budget",
                    session,
                )
                assert "plan_more_for_less" in response["tools"]
                summary = next(
                    b
                    for b in response["ui_blocks"]
                    if b["source_tool"] == "plan_more_for_less"
                )
                total = Decimal(
                    next(
                        m["value"] for m in summary["metrics"] if m["label"] == "Total"
                    )
                    .replace("Bs ", "")
                    .replace(",", "")
                )
                assert total <= budget and total == sum(
                    (catalog[c["id"]] for c in response["action_items"]), Decimal("0")
                )
                print(
                    "NVIDIA real: más prendas, total exacto dentro del presupuesto y componentes visuales.",
                    flush=True,
                )
                cart = await client.post(
                    "/cart/items", json={"variante_id": savings_origin, "cantidad": 1}
                )
                cart.raise_for_status()
                cart_before = cart.json()
                response = await ask(
                    socket,
                    "Busca ahorro real en mi carrito, conservando talla, color y cantidades, y si cabe una prenda extra con el ahorro. Solo propuesta.",
                    "saving",
                    session,
                )
                print(
                    "Ahorro: herramientas=",
                    response["tools"],
                    "vistas=",
                    [b["type"] for b in response["ui_blocks"]],
                    flush=True,
                )
                assert "find_cart_savings" in response["tools"]
                assert any(
                    b["source_tool"] == "find_cart_savings"
                    for b in response["ui_blocks"]
                )
                cart_after = (await client.get("/cart")).json()
                assert [
                    (r["variante_id"], r["cantidad"]) for r in cart_after["items"]
                ] == [(r["variante_id"], r["cantidad"]) for r in cart_before["items"]]
                print(
                    "NVIDIA real: ahorro consultado sin modificar el carrito.",
                    flush=True,
                )
                response = await ask(
                    socket,
                    "Quiero elegir sucursal para mi carrito, pero todavía no he indicado mi ciudad. Muéstrame un formulario para indicarla y espera mi confirmación.",
                    "ask-city",
                    session,
                )
                form = next(
                    b for b in response["ui_blocks"] if b["type"] == "shopping_question"
                )
                assert any(f["key"] == "city" for f in form["fields"])
                print(
                    "NVIDIA real: formulario de ciudad y turno detenido hasta confirmar.",
                    flush=True,
                )
                response = await ask(
                    socket,
                    f"{form['request']}\nDatos confirmados por mí: ciudad {city}. Continúa con recommend_pickup_branches para mi carrito.",
                    "resume-city",
                    session,
                )
                assert any(b["type"] == "branch_options" for b in response["ui_blocks"])
                print(
                    "NVIDIA real: búsqueda retomada y sucursales verificadas.",
                    flush=True,
                )
        finally:
            if user_id:
                with SessionLocal() as db:
                    db.execute(delete(User).where(User.id == user_id))
                    db.commit()
                print(
                    "Cuenta QA eliminada; catálogo y perfiles reales conservados.",
                    flush=True,
                )


if __name__ == "__main__":
    asyncio.run(main())
