from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Callable, Literal
import unicodedata

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Order, Product, ProductVariant, Reservation, User,
)
from app.services.store import cart_payload, get_product_detail, product_payload, search_products


class EmptyArgs(BaseModel):
    pass


class SearchProductsArgs(BaseModel):
    query: str | None = Field(default=None, max_length=150)
    category_id: int | None = None
    min_price: Decimal | None = Field(default=None, ge=0)
    max_price: Decimal | None = Field(default=None, ge=0)
    color: str | None = Field(default=None, max_length=60)
    size: str | None = Field(default=None, max_length=20)
    limit: int = Field(default=12, ge=1, le=30)


class ProductArgs(BaseModel):
    product_id: int


class StockArgs(BaseModel):
    product_id: int | None = None
    variant_id: int | None = None


class AlternativesArgs(BaseModel):
    product_id: int
    objective: Literal["lower_price", "quality_price", "similar_style"] = "similar_style"
    limit: int = Field(default=5, ge=1, le=10)


class CompareProductsArgs(BaseModel):
    product_ids: list[int] = Field(min_length=2, max_length=8)


class RecommendOutfitArgs(BaseModel):
    occasion: str = Field(default="casual", description="Ocasion: casual, cena, fiesta, formal, oficina, verano, cita")
    max_budget: float | None = Field(default=None, ge=0, description="Presupuesto maximo en Bs")
    gender: str | None = Field(default=None, description="HOMBRE, MUJER o UNISEX")
    top_size: str | None = Field(default=None, max_length=20)
    bottom_size: str | None = Field(default=None, max_length=20)
    shoe_size: str | None = Field(default=None, max_length=20)
    top_sizes: list[str] = Field(default_factory=list, max_length=4)
    bottom_sizes: list[str] = Field(default_factory=list, max_length=4)
    shoe_sizes: list[str] = Field(default_factory=list, max_length=4)
    top_type: str | None = Field(default=None, max_length=40)
    bottom_type: str | None = Field(default=None, max_length=40)
    bottom_fit: str | None = Field(default=None, max_length=40)
    measurements: dict[str, float] = Field(default_factory=dict)
    exclude_product_ids: list[int] = Field(default_factory=list, max_length=24)


class TrendingArgs(BaseModel):
    category_id: int | None = None
    limit: int = Field(default=8, ge=1, le=15)


class NewArrivalsArgs(BaseModel):
    limit: int = Field(default=8, ge=1, le=15)
    exclude_product_ids: list[int] = Field(default_factory=list, max_length=24)


class EvaluateGarmentFitArgs(BaseModel):
    product_id: int
    size: str = Field(default="M", max_length=10)
    user_chest: float | None = Field(default=None, ge=50, le=160)
    user_waist: float | None = Field(default=None, ge=40, le=160)
    user_height: float | None = Field(default=None, ge=120, le=230)


@dataclass
class ToolContext:
    db: Session
    user: User


@dataclass
class ToolDefinition:
    name: str
    description: str
    args_model: type[BaseModel]
    handler: Callable[[ToolContext, BaseModel], Any]

    def schema(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.args_model.model_json_schema(),
        }


def _search(context: ToolContext, raw: BaseModel) -> Any:
    args = SearchProductsArgs.model_validate(raw)
    return search_products(
        context.db,
        query=args.query,
        category_id=args.category_id,
        min_price=args.min_price,
        max_price=args.max_price,
        color=args.color,
        size=args.size,
        only_available=True,
        limit=args.limit,
    )


def _product(context: ToolContext, raw: BaseModel) -> Any:
    args = ProductArgs.model_validate(raw)
    return get_product_detail(context.db, args.product_id)


def _cart(context: ToolContext, raw: BaseModel) -> Any:
    cart = cart_payload(context.db, context.user.id)
    items = cart.get("items", [])
    if not items:
        return {
            "estado": "VACIO",
            "total_items": 0,
            "subtotal": 0.0,
            "items": [],
            "mensaje": "El carrito del usuario está actualmente vacío.",
        }
    items_summary = [
        f"{it['cantidad']}x {it['nombre']} (Color: {it['color']}, Talla: {it['talla']}) - Bs {float(it['subtotal']):.2f}"
        for it in items
    ]
    return {
        "estado": "CON_PRENDAS",
        "total_items": cart.get("total_items", 0),
        "subtotal": float(cart.get("subtotal", 0.0)),
        "resumen_texto": "; ".join(items_summary),
        "items": [
            {
                "producto_id": it["producto_id"],
                "id": it["id"],
                "variante_id": it["variante_id"],
                "nombre": it["nombre"],
                "sku": it["sku"],
                "color": it["color"],
                "talla": it["talla"],
                "cantidad": it["cantidad"],
                "precio_unitario": float(it["precio_unitario"]),
                "subtotal": float(it["subtotal"]),
                "stock_disponible": it["stock_disponible"],
                "imagen": it.get("imagen"),
            }
            for it in items
        ],
    }


def _stock(context: ToolContext, raw: BaseModel) -> Any:
    args = StockArgs.model_validate(raw)
    stmt = select(ProductVariant, Product).join(
        Product, Product.id == ProductVariant.producto_id
    )
    if args.variant_id:
        stmt = stmt.where(ProductVariant.id == args.variant_id)
    elif args.product_id:
        stmt = stmt.where(Product.id == args.product_id)
    else:
        return {"error": "product_id o variant_id es obligatorio"}
    rows = context.db.execute(stmt.order_by(ProductVariant.id).limit(30)).all()
    return [
        {
            "product_id": product.id,
            "product": product.nombre,
            "variant_id": variant.id,
            "sku": variant.sku,
            "color": variant.color,
            "size": variant.talla,
            "available": variant.stock_total - variant.stock_reservado,
        }
        for variant, product in rows
    ]


def _alternatives(context: ToolContext, raw: BaseModel) -> Any:
    args = AlternativesArgs.model_validate(raw)
    origin = context.db.get(Product, args.product_id)
    if not origin:
        return {"error": "Producto no encontrado"}
    stmt = (
        select(Product, ProductVariant)
        .join(ProductVariant, ProductVariant.producto_id == Product.id)
        .where(
            Product.id != origin.id,
            Product.categoria_id == origin.categoria_id,
            Product.activo.is_(True),
            ProductVariant.activo.is_(True),
            ProductVariant.stock_total > ProductVariant.stock_reservado,
        )
    )
    if args.objective == "lower_price":
        stmt = stmt.where(Product.precio < origin.precio).order_by(Product.precio)
    elif args.objective == "quality_price":
        stmt = stmt.order_by((Product.calidad_nivel / Product.precio).desc())
    else:
        stmt = stmt.order_by(
            (Product.marca == origin.marca).desc(),
            (Product.genero_objetivo == origin.genero_objetivo).desc(),
            Product.calidad_nivel.desc(),
        )
    rows = context.db.execute(stmt.limit(args.limit)).all()
    return [
        {
            "product_id": product.id,
            "variant_id": variant.id,
            "name": product.nombre,
            "price": float(product.precio),
            "quality": product.calidad_nivel,
            "saving": float(max(Decimal("0"), origin.precio - product.precio)),
            "color": variant.color,
            "size": variant.talla,
            "available": variant.stock_total - variant.stock_reservado,
        }
        for product, variant in rows
    ]


def _cart_totals(context: ToolContext, raw: BaseModel) -> Any:
    cart = cart_payload(context.db, context.user.id)
    return {
        "cart_id": cart["id"],
        "line_count": len(cart["items"]),
        "unit_count": cart["total_items"],
        "subtotal_bob": float(cart["subtotal"]),
        "lines": [
            {
                "name": item["nombre"],
                "quantity": item["cantidad"],
                "unit_price_bob": float(item["precio_unitario"]),
                "line_total_bob": float(item["subtotal"]),
            }
            for item in cart["items"]
        ],
        "calculated_by": "FastAPI Decimal",
    }


def _compare(context: ToolContext, raw: BaseModel) -> Any:
    args = CompareProductsArgs.model_validate(raw)
    products = context.db.scalars(
        select(Product).where(Product.id.in_(args.product_ids), Product.activo.is_(True))
    ).all()
    rows = []
    for product in products:
        value_index = (
            (Decimal(product.calidad_nivel) / product.precio).quantize(Decimal("0.0001"))
            if product.precio > 0
            else Decimal("0")
        )
        rows.append(
            {
                "product_id": product.id,
                "name": product.nombre,
                "price_bob": float(product.precio),
                "quality_level": product.calidad_nivel,
                "quality_price_index": float(value_index),
            }
        )
    rows.sort(key=lambda item: item["quality_price_index"], reverse=True)
    return {"ranking": rows, "calculated_by": "FastAPI Decimal"}


def _recommend_outfit(context: ToolContext, raw: BaseModel) -> Any:
    args = RecommendOutfitArgs.model_validate(raw)

    def normalized(value: Any) -> str:
        return "".join(
            char
            for char in unicodedata.normalize("NFKD", str(value or "").lower())
            if not unicodedata.combining(char)
        )

    all_available = search_products(context.db, only_available=True, limit=80)
    if args.gender and args.gender in ("HOMBRE", "MUJER", "UNISEX"):
        candidates = [p for p in all_available if p.get("genero_objetivo") in (args.gender, "UNISEX")]
    else:
        candidates = all_available
    if args.exclude_product_ids:
        excluded = set(args.exclude_product_ids)
        candidates = [p for p in candidates if p.get("id") not in excluded]
    if args.max_budget:
        candidates = [p for p in candidates if float(p.get("precio", 0)) <= args.max_budget]

    product_ids = [item["id"] for item in candidates]
    variants = context.db.scalars(
        select(ProductVariant)
        .where(
            ProductVariant.producto_id.in_(product_ids),
            ProductVariant.activo.is_(True),
            ProductVariant.stock_total > ProductVariant.stock_reservado,
        )
        .order_by(ProductVariant.producto_id, ProductVariant.id)
    ).all()
    variants_by_product: dict[int, list[ProductVariant]] = {}
    for variant in variants:
        variants_by_product.setdefault(variant.producto_id, []).append(variant)

    enriched = []
    for candidate in candidates:
        name = normalized(candidate["nombre"])
        if any(k in name for k in ["zapato", "zapatilla", "bota", "mocas", "chelsea", "oxford"]):
            requested_sizes = args.shoe_sizes or ([args.shoe_size] if args.shoe_size else [])
        elif any(k in name for k in ["jean", "pantalon", "jogger", "falda", "palazzo", "chino"]):
            requested_sizes = args.bottom_sizes or ([args.bottom_size] if args.bottom_size else [])
        elif any(k in name for k in ["polera", "camisa", "blusa", "polo", "hoodie"]):
            requested_sizes = args.top_sizes or ([args.top_size] if args.top_size else [])
        else:
            requested_sizes = []
        normalized_sizes = {str(value).upper() for value in requested_sizes}
        product_variants = variants_by_product.get(candidate["id"], [])
        variant = next(
            (
                item
                for item in product_variants
                if normalized_sizes and str(item.talla).upper() in normalized_sizes
            ),
            None,
        )
        if not normalized_sizes and product_variants:
            variant = product_variants[0]
        if not variant:
            continue
        item = dict(candidate)
        item.update(
            {
                "producto_id": candidate["id"],
                "variante_id": variant.id,
                "color": variant.color,
                "talla": variant.talla,
                "imagen": variant.imagen,
                "stock_variante": variant.stock_total - variant.stock_reservado,
            }
        )
        enriched.append(item)

    tops = [p for p in enriched if any(k in normalized(p["nombre"]) for k in ["polera", "camisa", "blusa", "polo", "hoodie"])]
    bottoms = [p for p in enriched if any(k in normalized(p["nombre"]) for k in ["jean", "pantalon", "jogger", "falda", "palazzo", "chino"])]
    footwear = [p for p in enriched if any(k in normalized(p["nombre"]) for k in ["zapato", "zapatilla", "bota", "mocas", "chelsea", "oxford"])]
    outerwear_acc = [p for p in enriched if any(k in normalized(p["nombre"]) for k in ["chamarra", "blazer", "chaqueta", "bomber", "cintur", "bolso", "reloj", "lentes", "bufanda", "vestido"])]

    restrictions = []
    if args.measurements:
        garment_measurements = {"pecho", "cintura", "cadera", "largo"}
        requested_garment_measurements = garment_measurements.intersection(
            args.measurements
        )
        if requested_garment_measurements:
            tops = []
            bottoms = []
            outerwear_acc = [
                item
                for item in outerwear_acc
                if any(
                    term in normalized(item["nombre"])
                    for term in ["cintur", "bolso", "reloj", "lentes", "bufanda"]
                )
            ]
            restrictions.append(
                "El catálogo no registra centímetros por variante para verificar "
                + ", ".join(sorted(requested_garment_measurements))
            )
        if "pie" in args.measurements:
            footwear = []
            restrictions.append(
                "El catálogo no registra largo de pie por variante para verificar el calzado"
            )
    if args.top_type:
        typed_tops = [p for p in tops if normalized(args.top_type) in normalized(p["nombre"])]
        if typed_tops:
            tops = typed_tops
        else:
            restrictions.append(f"No hay {args.top_type} disponible con las restricciones indicadas")
    if args.bottom_type:
        typed_bottoms = [
            p for p in bottoms if normalized(args.bottom_type) in normalized(p["nombre"])
        ]
        if typed_bottoms:
            bottoms = typed_bottoms
        else:
            restrictions.append(f"No hay {args.bottom_type} disponible con las restricciones indicadas")
    if args.bottom_fit:
        fit_terms = {
            "ancho": ["ancho", "wide", "palazzo", "relajado", "loose"],
            "recto": ["recto", "straight"],
            "ajustado": ["ajustado", "skinny", "slim"],
        }.get(args.bottom_fit, [args.bottom_fit])
        fitted_bottoms = [
            p
            for p in bottoms
            if any(
                normalized(term) in normalized(
                    " ".join(
                        [
                            str(p.get("nombre") or ""),
                            str(p.get("descripcion") or ""),
                            str(p.get("descripcion_ai") or ""),
                            " ".join(p.get("tags_ai") or []),
                        ]
                    )
                )
                for term in fit_terms
            )
        ]
        if fitted_bottoms:
            bottoms = fitted_bottoms
        else:
            restrictions.append(
                f"No hay pantalón de corte {args.bottom_fit} identificado en el catálogo"
            )
    top_sizes = args.top_sizes or ([args.top_size] if args.top_size else [])
    bottom_sizes = args.bottom_sizes or ([args.bottom_size] if args.bottom_size else [])
    shoe_sizes = args.shoe_sizes or ([args.shoe_size] if args.shoe_size else [])
    if top_sizes and not tops:
        restrictions.append(f"No hay parte superior en talla {' o '.join(top_sizes)}")
    if bottom_sizes and not bottoms:
        restrictions.append(f"No hay parte inferior en talla {' o '.join(bottom_sizes)}")
    if shoe_sizes and not footwear:
        restrictions.append(f"No hay calzado en talla {' o '.join(shoe_sizes)}")
    if args.exclude_product_ids and not any([tops, bottoms, footwear, outerwear_acc]):
        restrictions.append(
            "No hay otro outfit distinto con stock para estas restricciones"
        )

    return {
        "ocasion": args.occasion,
        "presupuesto_maximo": args.max_budget,
        "tops_sugeridos": tops[:4],
        "inferiores_sugeridos": bottoms[:4],
        "calzado_sugerido": footwear[:3],
        "complementos_abrigos": outerwear_acc[:4],
        "total_opciones": len(candidates),
        "restricciones_solicitadas": {
            "top_size": args.top_size,
            "bottom_size": args.bottom_size,
            "shoe_size": args.shoe_size,
            "top_sizes": top_sizes,
            "bottom_sizes": bottom_sizes,
            "shoe_sizes": shoe_sizes,
            "top_type": args.top_type,
            "bottom_type": args.bottom_type,
            "bottom_fit": args.bottom_fit,
            "measurements": args.measurements,
        },
        "restricciones_sin_stock": list(dict.fromkeys(restrictions)),
    }


def _new_arrivals(context: ToolContext, raw: BaseModel) -> Any:
    args = NewArrivalsArgs.model_validate(raw)
    excluded = set(args.exclude_product_ids)
    products = search_products(context.db, only_available=True, limit=40)
    return [product for product in products if product.get("id") not in excluded][
        : args.limit
    ]


def _most_expensive(context: ToolContext, raw: BaseModel) -> Any:
    row = context.db.execute(
        select(Product, ProductVariant)
        .join(ProductVariant, ProductVariant.producto_id == Product.id)
        .where(
            Product.activo.is_(True),
            ProductVariant.activo.is_(True),
            ProductVariant.stock_total > ProductVariant.stock_reservado,
        )
        .order_by(Product.precio.desc(), Product.calidad_nivel.desc(), Product.id)
        .limit(1)
    ).first()
    if not row:
        return []
    product, variant = row
    item = product_payload(
        product,
        variant.stock_total - variant.stock_reservado,
    )
    item["variante_representativa"] = {
        "id": variant.id,
        "color": variant.color,
        "talla": variant.talla,
        "imagen": variant.imagen,
    }
    return [item]


def _trending(context: ToolContext, raw: BaseModel) -> Any:
    args = TrendingArgs.model_validate(raw)
    stmt = (
        select(Product)
        .where(Product.activo.is_(True))
        .order_by(Product.calidad_nivel.desc(), Product.created_at.desc())
        .limit(args.limit)
    )
    if args.category_id:
        stmt = stmt.where(Product.categoria_id == args.category_id)
    products = context.db.scalars(stmt).all()
    return [
        {
            "id": p.id,
            "nombre": p.nombre,
            "marca": p.marca,
            "precio": float(p.precio),
            "calidad": p.calidad_nivel,
            "material": p.material,
            "descripcion": p.descripcion,
            "estilo_ai": p.descripcion_ai,
        }
        for p in products
    ]


def _orders(context: ToolContext, raw: BaseModel) -> Any:
    orders = context.db.scalars(
        select(Order)
        .where(Order.usuario_id == context.user.id)
        .order_by(Order.created_at.desc())
        .limit(10)
    ).all()
    return [
        {
            "id": order.id,
            "code": str(order.codigo_publico),
            "status": order.estado,
            "total_bob": float(order.total),
            "delivery": order.tipo_entrega,
            "created_at": order.created_at.isoformat(),
        }
        for order in orders
    ]


def _reservations(context: ToolContext, raw: BaseModel) -> Any:
    reservations = context.db.scalars(
        select(Reservation)
        .where(Reservation.usuario_id == context.user.id)
        .order_by(Reservation.created_at.desc())
        .limit(10)
    ).all()
    return [
        {
            "id": reservation.id,
            "code": str(reservation.codigo_publico),
            "status": reservation.estado,
            "expires_at": reservation.vence_at.isoformat(),
        }
        for reservation in reservations
    ]


def _evaluate_fit(context: ToolContext, raw: BaseModel) -> Any:
    args = EvaluateGarmentFitArgs.model_validate(raw)
    product = context.db.get(Product, args.product_id)
    if not product:
        return {"error": "Producto no encontrado"}

    size = args.size.upper()
    size_chest_map = {
        "XS": 90.0, "S": 96.0, "M": 102.0, "L": 108.0, "XL": 114.0, "XXL": 120.0,
        "28": 92.0, "30": 96.0, "32": 102.0, "34": 108.0, "36": 114.0, "38": 120.0,
    }
    garment_chest = size_chest_map.get(size, 102.0)
    user_chest = args.user_chest or 96.0
    ease = garment_chest - user_chest

    if ease < 0:
        fit_type = "MUY_AJUSTADO"
        comment = f"La talla {size} quedará ceñida al cuerpo con tensión en costuras ({ease:+.1f}cm)."
    elif ease <= 3.0:
        fit_type = "SLIM_FIT"
        comment = f"La talla {size} ofrece un corte estructurado y entallado (+{ease:.1f}cm de holgura)."
    elif ease <= 7.0:
        fit_type = "IDEAL_SASTRERO"
        comment = f"Ajuste sastrero óptimo. Permite movimiento natural y caída limpia (+{ease:.1f}cm de holgura)."
    else:
        fit_type = "OVERSIZE_RELAJADO"
        comment = f"Silueta holgada y moderna estilo drapeado (+{ease:.1f}cm de holgura)."

    return {
        "producto_id": product.id,
        "nombre": product.nombre,
        "talla_evaluada": size,
        "pecho_prenda_cm": garment_chest,
        "pecho_usuario_cm": user_chest,
        "holgura_cm": round(ease, 1),
        "tipo_calce": fit_type,
        "dictamen_estilista": comment,
    }


TOOLS = {
    tool.name: tool
    for tool in [
        ToolDefinition(
            "search_products",
            "Busca prendas reales en el catálogo con filtros de nombre, categoría, presupuesto, color o talla.",
            SearchProductsArgs,
            _search,
        ),
        ToolDefinition(
            "get_product_detail",
            "Obtiene información detallada de una prenda: material, variantes, colores, tallas y stock.",
            ProductArgs,
            _product,
        ),
        ToolDefinition(
            "get_my_cart",
            "Lee todas las prendas que el usuario tiene actualmente en su carrito (nombre, talla, color, precio y total). Usar siempre que el usuario pregunte por su carrito, bolsa o qué tiene guardado.",
            EmptyArgs,
            _cart,
        ),
        ToolDefinition(
            "recommend_outfit",
            "Arma outfits completos armonizados (top + inferior + calzado + accesorios) según ocasión (cena, fiesta, casual, oficina) y presupuesto.",
            RecommendOutfitArgs,
            _recommend_outfit,
        ),
        ToolDefinition(
            "get_trending_pieces",
            "Obtiene las piezas más destacadas, de mayor calidad (Q5/Q4) y tendencia del atelier.",
            TrendingArgs,
            _trending,
        ),
        ToolDefinition(
            "get_new_arrivals",
            "Obtiene novedades del catálogo con stock y evita repetir recomendaciones recientes de la conversación.",
            NewArrivalsArgs,
            _new_arrivals,
        ),
        ToolDefinition(
            "get_most_expensive_product",
            "Devuelve exactamente una prenda: la de mayor precio con una variante disponible. No arma outfits.",
            EmptyArgs,
            _most_expensive,
        ),
        ToolDefinition(
            "get_stock",
            "Consulta stock real disponible por producto o variante.",
            StockArgs,
            _stock,
        ),
        ToolDefinition(
            "find_alternatives",
            "Busca alternativas con stock para ahorrar, mejorar calidad o mantener el mismo estilo.",
            AlternativesArgs,
            _alternatives,
        ),
        ToolDefinition(
            "calculate_cart_totals",
            "Calcula cantidades, subtotales y líneas exactas del carrito de compras.",
            EmptyArgs,
            _cart_totals,
        ),
        ToolDefinition(
            "compare_products",
            "Compara precio y calidad entre múltiples prendas de forma objetiva.",
            CompareProductsArgs,
            _compare,
        ),
        ToolDefinition(
            "get_my_orders",
            "Consulta los últimos pedidos y estados de compra del usuario autenticado.",
            EmptyArgs,
            _orders,
        ),
        ToolDefinition(
            "get_my_reservations",
            "Consulta reservas activas y fechas de vencimiento del usuario.",
            EmptyArgs,
            _reservations,
        ),
        ToolDefinition(
            "evaluate_garment_fit",
            "Calcula la holgura en cm, caída sastrera y tensión de una talla específica para el probador AR.",
            EvaluateGarmentFitArgs,
            _evaluate_fit,
        ),
    ]
}



def tool_catalog() -> list[dict]:
    return [tool.schema() for tool in TOOLS.values()]


def execute_tool(name: str, arguments: dict, context: ToolContext) -> Any:
    tool = TOOLS.get(name)
    if not tool:
        return {"error": f"Tool no permitida: {name}"}
    validated = tool.args_model.model_validate(arguments)
    return tool.handler(context, validated)
