"""Read-only, authenticated shopping capabilities; no model-authored commercial facts."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import unicodedata

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from app.models import (
    Address,
    Branch,
    BranchStock,
    Category,
    City,
    Favorite,
    Product,
    ProductVariant,
    UserStyleProfile,
)
from app.services.store import cart_payload, normalize_gender

ZERO = Decimal("0")
SCAN_LIMIT = 2000


def norm(value):
    return "".join(
        c
        for c in unicodedata.normalize("NFKD", str(value or "").casefold())
        if not unicodedata.combining(c)
    ).strip()


class ShoppingArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    presentation: str = Field(default="auto", pattern="^(auto|continue)$")


class DiscoverArgs(ShoppingArgs):
    query: str | None = Field(
        default=None,
        max_length=150,
        description="Solo términos de la prenda, no el mensaje completo.",
    )
    category_id: int | None = Field(default=None, gt=0)
    gender: str | None = Field(default=None, max_length=30)
    size: str | None = Field(default=None, max_length=20)
    size_group: str | None = Field(
        default=None, pattern="^(upper|lower|footwear|accessory)$"
    )
    top_size: str | None = Field(default=None, max_length=20)
    bottom_size: str | None = Field(default=None, max_length=20)
    shoe_size: str | None = Field(default=None, max_length=20)
    color: str | None = Field(default=None, max_length=60)
    styles: list[str] | None = Field(default=None, max_length=6)
    max_price: Decimal | None = Field(default=None, ge=0, le=1000000)
    use_profile: bool = True
    recent_days: int | None = Field(default=None, ge=1, le=90)
    exclude_product_ids: list[int] = Field(default_factory=list, max_length=30)
    limit: int = Field(default=4, ge=1, le=6)


class MoreForLessArgs(DiscoverArgs):
    budget: Decimal | None = Field(default=None, ge=0, le=1000000)
    max_items: int = Field(default=6, ge=1, le=6)


class BranchAdviceArgs(ShoppingArgs):
    variant_ids: list[int] = Field(default_factory=list, max_length=12)
    city: str | None = Field(default=None, max_length=100)


class CartSavingsArgs(ShoppingArgs):
    keep_color: bool = True
    extra_items: int = Field(default=2, ge=0, le=3)


def shopping_context(db, user):
    profile = db.scalar(
        select(UserStyleProfile).where(UserStyleProfile.usuario_id == user.id)
    )
    address = db.scalar(
        select(Address)
        .where(Address.usuario_id == user.id)
        .order_by(Address.es_principal.desc(), Address.id)
        .limit(1)
    )
    fields = (
        "genero",
        "talla_superior",
        "talla_inferior",
        "talla_calzado",
        "estilos_preferidos",
        "colores_favoritos",
        "ocasiones_frecuentes",
        "presupuesto_habitual",
        "silueta_preferida",
    )
    preferences = (
        {key: getattr(profile, key) for key in fields}
        if isinstance(profile, UserStyleProfile)
        else {}
    )
    preferences = {
        key: str(v) if isinstance(v, Decimal) else v
        for key, v in preferences.items()
        if v is not None
    }
    categories = [
        {"id": c.id, "name": c.nombre}
        for c in db.scalars(
            select(Category)
            .where(Category.activo.is_(True))
            .order_by(Category.id)
            .limit(100)
        )
    ]
    return {
        "profile": preferences,
        "city": address.ciudad if isinstance(address, Address) else None,
        "categories": categories,
        "profile_available": bool(preferences),
        "precedence": "Petición explícita > preferencias de esta conversación > perfil guardado. No cambiar el perfil al buscar.",
        "missing": [
            key
            for key in ("talla_superior", "talla_inferior", "talla_calzado")
            if not preferences.get(key)
        ],
    }


def get_context(context, _args):
    return shopping_context(context.db, context.user)


def _preferences(context, args):
    saved = shopping_context(context.db, context.user)
    profile = saved["profile"] if args.use_profile else {}
    session = (getattr(context, "preferences", None) or {}) if args.use_profile else {}

    def choice(name, profile_key=None):
        explicit = getattr(args, name, None)
        return (
            explicit
            if explicit is not None
            else session.get(name, profile.get(profile_key or name))
        )

    return {
        "gender": choice("gender", "genero"),
        "top_size": choice("top_size", "talla_superior"),
        "bottom_size": choice("bottom_size", "talla_inferior"),
        "shoe_size": choice("shoe_size", "talla_calzado"),
        "color": choice("color"),
        "colors": profile.get("colores_favoritos") or [],
        "styles": choice("styles", "estilos_preferidos") or [],
        "max_price": args.max_price
        if args.max_price is not None
        else (
            getattr(args, "budget", None)
            if getattr(args, "budget", None) is not None
            else choice("max_price", "presupuesto_habitual")
        ),
        "budget": choice("budget", "presupuesto_habitual"),
        "city": saved["city"],
    }


def _group(category, name):
    # Classification of catalog attributes, never parsing customer intentions.
    families = {
        "footwear": (
            "shoe",
            "boot",
            "sneaker",
            "sandal",
            "heel",
            "calzado",
            "zapato",
            "zapatilla",
            "bota",
            "sandalia",
            "mocasin",
            "loafer",
            "sneaker",
            "chelsea",
        ),
        "lower": (
            "trouser",
            "pant",
            "skirt",
            "short",
            "legging",
            "pantalon",
            "jean",
            "falda",
            "short",
            "bermuda",
            "jogger",
            "palazzo",
            "legging",
        ),
        "accessory": (
            "bag",
            "belt",
            "scarf",
            "hat",
            "accesorio",
            "bolso",
            "cinturon",
            "bufanda",
            "gorra",
            "sombrero",
            "cartera",
            "collar",
        ),
        "upper": (
            "shirt",
            "blouse",
            "sweater",
            "dress",
            "jacket",
            "blazer",
            "coat",
            "bra",
            "camisa",
            "polera",
            "blusa",
            "chamarra",
            "hoodie",
            "sueter",
            "polo",
            "top",
            "remera",
            "vestido",
            "chaqueta",
            "abrigo",
            "sudadera",
        ),
    }
    return next(
        (
            group
            for text in (norm(category), norm(name))
            for group, terms in families.items()
            if any(term in text for term in terms)
        ),
        None,
    )


def _record(product, variant, reasons):
    return {
        "id": product.id,
        "producto_id": product.id,
        "variante_id": variant.id,
        "categoria_id": product.categoria_id,
        "genero_objetivo": str(
            getattr(product.genero_objetivo, "value", product.genero_objetivo)
        ),
        "calidad_nivel": product.calidad_nivel,
        "material": product.material,
        "nombre": product.nombre,
        "precio": str(product.precio),
        "talla": variant.talla,
        "color": variant.color,
        "imagen": variant.imagen or (product.imagenes or [None])[0],
        "stock_disponible": variant.stock_total - variant.stock_reservado,
        "reasons": reasons,
        "motivo": " · ".join(reasons)[:300],
        "accion": "AGREGAR",
    }


def _candidates(context, args, *, cheapest=False):
    prefs = _preferences(context, args)
    stmt = (
        select(Product, ProductVariant, Category)
        .join(ProductVariant, ProductVariant.producto_id == Product.id)
        .join(Category, Category.id == Product.categoria_id)
        .where(
            Product.activo.is_(True),
            Category.activo.is_(True),
            ProductVariant.activo.is_(True),
            ProductVariant.stock_total > ProductVariant.stock_reservado,
        )
    )
    if args.category_id:
        stmt = stmt.where(Product.categoria_id == args.category_id)
    gender = normalize_gender(prefs["gender"])
    if gender and gender.value != "UNISEX":
        stmt = stmt.where(Product.genero_objetivo.in_([gender, "UNISEX"]))
    if prefs["max_price"] is not None:
        stmt = stmt.where(Product.precio <= Decimal(str(prefs["max_price"])))
    if args.size is not None:
        stmt = stmt.where(func.lower(ProductVariant.talla) == args.size.strip().lower())
    if prefs["color"]:
        stmt = stmt.where(ProductVariant.color.ilike(f"%{prefs['color']}%"))
    if args.recent_days:
        stmt = stmt.where(
            Product.created_at <= datetime.now(timezone.utc),
            Product.created_at
            >= datetime.now(timezone.utc) - timedelta(days=args.recent_days),
        )
    if args.exclude_product_ids:
        stmt = stmt.where(Product.id.not_in(args.exclude_product_ids))
    # Every term must match actual catalog text; no unrelated fallback catalog.
    for term in (args.query or "").split()[:12]:
        blob = func.concat(
            Product.nombre,
            " ",
            Product.descripcion,
            " ",
            Product.material,
            " ",
            Category.nombre,
            " ",
            func.array_to_string(Product.tags_ai, " "),
        )
        stmt = stmt.where(blob.ilike(f"%{term}%"))
    order = (
        (Product.precio, Product.id, ProductVariant.id)
        if cheapest
        else (Product.created_at.desc(), Product.id, ProductVariant.id)
    )
    rows = list(context.db.execute(stmt.order_by(*order).limit(SCAN_LIMIT + 1)))
    truncated = len(rows) > SCAN_LIMIT
    favorites = set(
        context.db.scalars(
            select(Favorite.producto_id).where(Favorite.usuario_id == context.user.id)
        )
    )
    choices = {}
    missing_sizes = set()
    for product, variant, category in rows[:SCAN_LIMIT]:
        group = args.size_group or _group(category.nombre, product.nombre)
        if (
            not group
            and not args.size
            and any(prefs.get(k) for k in ("top_size", "bottom_size", "shoe_size"))
        ):
            missing_sizes.add("prendas sin familia de talla identificable")
            continue
        expected = args.size or prefs.get(
            {"upper": "top_size", "lower": "bottom_size", "footwear": "shoe_size"}.get(
                group
            )
        )
        if expected and norm(variant.talla) != norm(expected):
            continue
        if not expected and group != "accessory":
            missing_sizes.add(group or "prenda sin familia registrada")
        reasons = [
            f"Talla {variant.talla} disponible"
            if expected
            else f"Talla disponible: {variant.talla}; confirma tu talla"
        ]
        score = 0
        if any(norm(c) == norm(variant.color) for c in prefs["colors"]):
            reasons.append("Coincide con uno de tus colores favoritos")
            score += 3
        catalog_text = norm(
            f"{product.nombre} {product.descripcion or ''} {' '.join(product.tags_ai or [])}"
        )
        for style in prefs["styles"]:
            if norm(style) and norm(style) in catalog_text:
                reasons.append(f"Estilo registrado: {style}")
                score += 2
        if product.id in favorites:
            reasons.append("Ya está en tus favoritos")
            score += 1
        created = product.created_at
        if created and created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        is_recent = bool(created and now - timedelta(days=30) <= created <= now)
        if args.recent_days:
            reasons.append(
                f"Ingresó al catálogo en los últimos {args.recent_days} días"
            )
        elif is_recent:
            reasons.append("Novedad del catálogo: ingresó en los últimos 30 días")
        record = _record(product, variant, reasons)
        record["is_recent"] = is_recent
        record["_created"] = created.timestamp() if created else 0
        record["_score"] = score
        if product.id not in choices or choices[product.id]["_score"] < score:
            choices[product.id] = record
    records = list(choices.values())
    records.sort(
        key=lambda r: (Decimal(r["precio"]), -r["_score"], r["id"])
        if cheapest
        else (-r["_score"], -r["_created"], r["id"])
    )
    for row in records:
        row.pop("_score")
        row.pop("_created")
    criteria = [f"Género: {prefs['gender']}"] if prefs["gender"] else []
    for key, label in [
        ("top_size", "Superior"),
        ("bottom_size", "Inferior"),
        ("shoe_size", "Calzado"),
    ]:
        if prefs[key]:
            criteria.append(f"{label}: {prefs[key]}")
    if args.size:
        criteria.append(f"Talla solicitada: {args.size}")
    if prefs["color"]:
        criteria.append(f"Color solicitado: {prefs['color']}")
    if prefs["max_price"] is not None:
        criteria.append(f"Tope por prenda: Bs {Decimal(str(prefs['max_price'])):.2f}")
    return records, prefs, criteria, truncated, sorted(missing_sizes)


def discover(context, raw):
    args = DiscoverArgs.model_validate(raw)
    records, prefs, criteria, truncated, missing = _candidates(context, args)
    return {
        "products": records[: args.limit],
        "criteria": criteria,
        "missing_sizes": missing,
        "recent_days": args.recent_days,
        "matched_count": len(records),
        "truncated": truncated,
        "note": "Coincidencias basadas en talla, catálogo y preferencias; el ajuste físico requiere probar la prenda.",
    }


def plan_more(context, raw):
    args = MoreForLessArgs.model_validate(raw)
    records, prefs, criteria, truncated, missing = _candidates(
        context, args, cheapest=True
    )
    if prefs["budget"] is None:
        return {
            "error": "No hay presupuesto guardado. Pregunta cuánto quiere gastar antes de calcular el plan."
        }
    budget = Decimal(str(prefs["budget"]))
    selected, total = [], ZERO
    for row in records:
        price = Decimal(row["precio"])
        if total + price <= budget and len(selected) < args.max_items:
            selected.append(row)
            total += price
    return {
        "products": selected,
        "criteria": criteria,
        "budget": str(budget),
        "total": str(total),
        "remaining": str(budget - total),
        "item_count": len(selected),
        "truncated": truncated,
        "missing_sizes": missing,
        "note": "Una unidad por prenda, priorizando precios menores entre las coincidencias consultadas. No incluye envío ni descuentos no confirmados; no modifica el carrito.",
    }


def branch_advice(context, raw):
    args = BranchAdviceArgs.model_validate(raw)
    requested = {identity: 1 for identity in args.variant_ids}
    if not requested:
        cart = cart_payload(context.db, context.user.id)
        requested = {r["variante_id"]: r["cantidad"] for r in cart["items"]}
    if not requested:
        return {
            "error": "El carrito está vacío. Consulta prendas y pide sus variantes antes de recomendar una sucursal."
        }
    active = set(
        context.db.scalars(
            select(ProductVariant.id)
            .join(Product, Product.id == ProductVariant.producto_id)
            .where(
                ProductVariant.id.in_(requested),
                ProductVariant.activo.is_(True),
                Product.activo.is_(True),
            )
        )
    )
    if active != set(requested):
        return {
            "error": "Alguna variante ya no está activa. Vuelve a consultar la selección."
        }
    city = (
        args.city
        or (getattr(context, "preferences", None) or {}).get("city")
        or shopping_context(context.db, context.user)["city"]
    )
    if not city:
        return {
            "error": "Falta confirmar la ciudad. Usa ask_shopping_preferences con goal=branches y fields=[city], sin inventar ubicación."
        }
    stocks = {
        (s.sucursal_id, s.variante_id): s.stock_total - s.stock_reservado
        for s in context.db.scalars(
            select(BranchStock).where(
                BranchStock.variante_id.in_(requested), BranchStock.activo.is_(True)
            )
        )
    }
    branches = []
    for branch, location in context.db.execute(
        select(Branch, City)
        .join(City, City.id == Branch.ciudad_id)
        .where(Branch.activo.is_(True), City.activo.is_(True))
    ):
        covered = sum(
            stocks.get((branch.id, variant), 0) >= qty
            for variant, qty in requested.items()
        )
        branches.append(
            {
                "id": branch.id,
                "name": branch.nombre,
                "address": branch.direccion,
                "city": location.nombre,
                "covered": covered,
                "requested": len(requested),
                "same_city": bool(city and norm(city) == norm(location.nombre)),
                "complete": covered == len(requested),
            }
        )
    branches.sort(
        key=lambda b: (-b["complete"], -b["same_city"], -b["covered"], b["id"])
    )
    return {
        "branches": branches[:6],
        "city": city,
        "note": "Se prioriza reunir la selección completa y tu ciudad, después la cobertura de stock. No hay estimación de distancia o tiempo de viaje. Stock sin reservar.",
    }


def cart_savings(context, raw):
    args = CartSavingsArgs.model_validate(raw)
    cart = cart_payload(context.db, context.user.id)
    if not cart["items"]:
        return {
            "error": "Tu carrito está vacío. Usa plan_more_for_less para explorar prendas con un presupuesto."
        }
    changes, products, allocations = [], [], {}
    before, after = ZERO, ZERO
    for line in cart["items"]:
        origin = context.db.get(Product, line["producto_id"], populate_existing=True)
        variant = context.db.get(
            ProductVariant, line["variante_id"], populate_existing=True
        )
        if not origin or not variant or not origin.activo or not variant.activo:
            return {
                "error": "Una prenda del carrito ya no está activa. Revisa el carrito antes de calcular ahorro."
            }
        qty = line["cantidad"]
        before += origin.precio * qty
        stmt = (
            select(Product, ProductVariant)
            .join(ProductVariant, ProductVariant.producto_id == Product.id)
            .where(
                Product.activo.is_(True),
                ProductVariant.activo.is_(True),
                Product.categoria_id == origin.categoria_id,
                Product.precio < origin.precio,
                func.lower(ProductVariant.talla) == variant.talla.lower(),
                ProductVariant.stock_total - ProductVariant.stock_reservado >= qty,
                Product.genero_objetivo.in_([origin.genero_objetivo, "UNISEX"]),
            )
        )
        if args.keep_color:
            stmt = stmt.where(func.lower(ProductVariant.color) == variant.color.lower())
        replacement = next(
            (
                (p, v)
                for p, v in context.db.execute(
                    stmt.order_by(Product.precio, Product.id, ProductVariant.id).limit(
                        200
                    )
                )
                if v.stock_total - v.stock_reservado - allocations.get(v.id, 0) >= qty
            ),
            None,
        )
        product, chosen = replacement or (origin, variant)
        if (
            chosen.stock_total - chosen.stock_reservado - allocations.get(chosen.id, 0)
            < qty
        ):
            return {
                "error": "El stock actual no alcanza para conservar las cantidades del carrito."
            }
        allocations[chosen.id] = allocations.get(chosen.id, 0) + qty
        after += product.precio * qty
        if replacement:
            changes.append(
                {
                    "from": origin.nombre,
                    "to": product.nombre,
                    "quantity": qty,
                    "saving": str((origin.precio - product.precio) * qty),
                    "detail": f"Misma categoría y talla {chosen.talla}"
                    + (
                        f", color {chosen.color}"
                        if args.keep_color
                        else "; color alternativo"
                    ),
                }
            )
        products.append(
            _record(
                product,
                chosen,
                [
                    f"{qty} unidad(es) para tu carrito",
                    "Alternativa de menor precio"
                    if replacement
                    else "Conserva tu prenda actual",
                ],
            )
        )
    extras = []
    if args.extra_items and before > after:
        candidates, _, _, _, _ = _candidates(context, DiscoverArgs(), cheapest=True)
        selected_ids = {p["id"] for p in products}
        extra_total = ZERO
        for row in candidates:
            if (
                row["id"] not in selected_ids
                and after + extra_total + Decimal(row["precio"]) <= before
            ):
                extras.append(row)
                row["motivo"] = (
                    "Prenda extra que cabe en el ahorro calculado · " + row["motivo"]
                )
                selected_ids.add(row["id"])
                extra_total += Decimal(row["precio"])
            if len(extras) >= args.extra_items:
                break
    else:
        extra_total = ZERO
    return {
        "products": products[:6],
        "extras": extras,
        "changes": changes,
        "before": str(before),
        "after": str(after),
        "saving": str(before - after),
        "extra_total": str(extra_total),
        "total_with_extras": str(after + extra_total),
        "remaining": str(before - after - extra_total),
        "note": "Comparación con precios actuales del catálogo y las cantidades del carrito. Alternativas de la misma categoría y talla; revisa material y calidad. Propuesta sin aplicar cambios ni cupones.",
    }


def render_shopping_data(name, data):
    """Canonical facts kept in server history and used for explicit text responses."""
    if name == "get_my_shopping_context":
        import json

        return "Tus preferencias guardadas: " + json.dumps(
            data, ensure_ascii=False, default=str
        )
    if name == "recommend_pickup_branches":
        return (
            "\n".join(
                f"{r['name']} · {r['city']} · {r['address']} · {r['covered']}/{r['requested']} variantes con stock suficiente"
                for r in data["branches"]
            )
            + "\n"
            + data["note"]
        )
    lines = list(data.get("criteria", []))
    lines += [
        f"{p['nombre']} · {p['color']} · talla {p['talla']} · Bs {Decimal(p['precio']):.2f} · variante #{p['variante_id']} · {'; '.join(p['reasons'])}"
        for p in data.get("products", []) + data.get("extras", [])
    ]
    if name == "plan_more_for_less":
        lines += [
            f"Presupuesto: Bs {Decimal(data['budget']):.2f}; total: Bs {Decimal(data['total']):.2f}; saldo: Bs {Decimal(data['remaining']):.2f}; {data['item_count']} prendas."
        ]
    if name == "find_cart_savings":
        lines += [
            f"Carrito actual: Bs {Decimal(data['before']):.2f}; propuesta: Bs {Decimal(data['after']):.2f}; ahorro por sustitución: Bs {Decimal(data['saving']):.2f}; total con extras: Bs {Decimal(data['total_with_extras']):.2f}."
        ]
        lines += [
            f"{c['quantity']} × {c['from']} por {c['to']}: ahorro Bs {Decimal(c['saving']):.2f}. {c['detail']}"
            for c in data["changes"]
        ]
    return "\n".join(lines + [data["note"]])
