from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Callable, Literal
import unicodedata

from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    Branch, BranchStock, Favorite, Order, Payment, Product, ProductVariant, Reservation, User,
)
from app.services.store import cart_payload, get_product_detail, product_payload, search_products


class EmptyArgs(BaseModel):
    pass


class SearchProductsArgs(BaseModel):
    query: str | None = Field(default=None, max_length=150)
    category_id: int | None = Field(default=None, json_schema_extra={"x-context-only": True})
    min_price: Decimal | None = Field(default=None, ge=0)
    max_price: Decimal | None = Field(default=None, ge=0)
    color: str | None = Field(default=None, max_length=60, json_schema_extra={"x-user-grounded": True})
    size: str | None = Field(default=None, max_length=20, json_schema_extra={"x-user-grounded": True})
    limit: int = Field(default=12, ge=1, le=30)


class ProductArgs(BaseModel):
    product_id: int


class BranchAvailabilityArgs(BaseModel):
    product_id: int = Field(gt=0)
    size: str | None = Field(default=None, max_length=20)
    color: str | None = Field(default=None, max_length=60)


class OrderPaymentArgs(BaseModel):
    order_id: int = Field(gt=0)


class SelectionBudgetArgs(BaseModel):
    variant_ids: list[int] = Field(min_length=1, max_length=20)
    budget: Decimal = Field(ge=0, max_digits=10, decimal_places=2)


def _favorites(context: "ToolContext", raw: BaseModel) -> Any:
    products = context.db.scalars(select(Product).join(Favorite, Favorite.producto_id == Product.id).where(
        Favorite.usuario_id == context.user.id, Product.activo.is_(True),
    ).order_by(Product.id.desc()).limit(20))
    return [get_product_detail(context.db, product.id) for product in products]


def _branch_availability(context: "ToolContext", raw: BaseModel) -> Any:
    args = BranchAvailabilityArgs.model_validate(raw)
    stmt = select(Branch, BranchStock, ProductVariant).join(
        BranchStock, BranchStock.sucursal_id == Branch.id,
    ).join(ProductVariant, ProductVariant.id == BranchStock.variante_id).join(
        Product, Product.id == ProductVariant.producto_id,
    ).where(
        Product.id == args.product_id, Product.activo.is_(True), Branch.activo.is_(True),
        BranchStock.activo.is_(True), ProductVariant.activo.is_(True),
        BranchStock.stock_total > BranchStock.stock_reservado,
    )
    if args.size:
        stmt = stmt.where(ProductVariant.talla.ilike(args.size))
    if args.color:
        stmt = stmt.where(ProductVariant.color.ilike(args.color))
    return [{"sucursal": branch.nombre, "direccion": branch.direccion, "sucursal_id": branch.id,
             "variante_id": variant.id, "talla": variant.talla, "color": variant.color,
             "disponible": stock.stock_total - stock.stock_reservado}
            for branch, stock, variant in context.db.execute(stmt.order_by(Branch.id, ProductVariant.id).limit(40))]


def _my_payment_status(context: "ToolContext", raw: BaseModel) -> Any:
    args = OrderPaymentArgs.model_validate(raw)
    order = context.db.scalar(select(Order).where(Order.id == args.order_id, Order.usuario_id == context.user.id))
    if not order:
        return {"error": "Pedido no encontrado en tu cuenta"}
    rows = context.db.scalars(select(Payment).where(Payment.pedido_id == order.id).order_by(Payment.id.desc()).limit(10))
    return {"pedido_id": order.id, "estado_pedido": order.estado, "total": str(order.total),
            "pagos": [{"estado": p.estado, "metodo": p.metodo, "monto": str(p.monto)} for p in rows],
            "nota": "Estado registrado en el servidor. Esta consulta no verifica el banco ni confirma pagos."}


def _selection_budget(context: "ToolContext", raw: BaseModel) -> Any:
    args = SelectionBudgetArgs.model_validate(raw)
    if len(args.variant_ids) != len(set(args.variant_ids)):
        return {"error": "Indica cada variante una sola vez; se calcula una unidad por prenda"}
    rows = context.db.execute(select(ProductVariant, Product).join(Product, Product.id == ProductVariant.producto_id).where(
        ProductVariant.id.in_(args.variant_ids), ProductVariant.activo.is_(True), Product.activo.is_(True),
    )).all()
    if len(rows) != len(args.variant_ids):
        return {"error": "Una o más variantes ya no están disponibles"}
    total = sum((product.precio for _, product in rows), Decimal("0"))
    return {"total": str(total), "presupuesto": str(args.budget), "saldo": str(args.budget - total),
            "dentro_presupuesto": total <= args.budget,
            "stock_verificado": all(v.stock_total > v.stock_reservado for v, _ in rows),
            "prendas": [{"producto_id": p.id, "nombre": p.nombre, "variante_id": v.id,
                         "talla": v.talla, "color": v.color, "precio": str(p.precio)} for v, p in rows]}


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
    base_product_id: int | None = Field(default=None, description="ID numerico de la prenda base unicamente si el usuario solicito completar un producto especifico")
    product_id: int | None = Field(default=None, description="ID numerico de prenda base (alias de base_product_id)")
    occasion: str | None = Field(default=None, description="Ocasion o estilo indicado por el usuario; no asumir", json_schema_extra={"x-user-grounded": True})
    max_budget: float | None = Field(default=None, ge=0, description="Presupuesto maximo en Bs")
    gender: str | None = Field(default=None, description="HOMBRE, MUJER o UNISEX")
    top_size: str | None = Field(default=None, max_length=20, description="Talla de camisa o polera", json_schema_extra={"x-user-grounded": True})
    bottom_size: str | None = Field(default=None, max_length=20, description="Talla del pantalón o falda", json_schema_extra={"x-user-grounded": True})
    shoe_size: str | None = Field(default=None, max_length=20, description="Talla del calzado", json_schema_extra={"x-user-grounded": True})
    top_sizes: list[str] = Field(default_factory=list, max_length=4, json_schema_extra={"x-user-grounded": True})
    bottom_sizes: list[str] = Field(default_factory=list, max_length=4, json_schema_extra={"x-user-grounded": True})
    shoe_sizes: list[str] = Field(default_factory=list, max_length=4, json_schema_extra={"x-user-grounded": True})
    top_type: str | None = Field(default=None, max_length=40)
    bottom_type: str | None = Field(default=None, max_length=40)
    bottom_fit: str | None = Field(default=None, max_length=40)
    measurements: dict[str, float] = Field(default_factory=dict, json_schema_extra={"x-context-only": True})
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
    read_only: bool = False
    # Optional server-owned presentation adapter; a new capability needs no agent branch.
    card_renderer: Callable[[ToolContext, dict, Any], list[dict]] | None = None

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

    target_base_id = args.base_product_id or args.product_id
    base_item = None
    if target_base_id:
        base_prod = context.db.scalar(
            select(Product).where(Product.id == target_base_id, Product.activo.is_(True))
        )
        if base_prod:
            base_var = None
            if args.top_size:
                base_var = context.db.scalar(
                    select(ProductVariant).where(
                        ProductVariant.producto_id == base_prod.id,
                        ProductVariant.activo.is_(True),
                        ProductVariant.stock_total > ProductVariant.stock_reservado,
                        func.upper(ProductVariant.talla) == args.top_size.strip().upper(),
                    )
                )
            if not base_var and args.bottom_size:
                base_var = context.db.scalar(
                    select(ProductVariant).where(
                        ProductVariant.producto_id == base_prod.id,
                        ProductVariant.activo.is_(True),
                        ProductVariant.stock_total > ProductVariant.stock_reservado,
                        func.upper(ProductVariant.talla) == args.bottom_size.strip().upper(),
                    )
                )
            if not base_var:
                base_var = context.db.scalar(
                    select(ProductVariant).where(
                        ProductVariant.producto_id == base_prod.id,
                        ProductVariant.activo.is_(True),
                        ProductVariant.stock_total > ProductVariant.stock_reservado,
                    ).order_by(ProductVariant.id)
                )
            if base_var:
                base_item = {
                    "id": base_prod.id,
                    "producto_id": base_prod.id,
                    "nombre": base_prod.nombre,
                    "precio": float(base_prod.precio),
                    "variante_id": base_var.id,
                    "color": base_var.color,
                    "talla": base_var.talla,
                    "imagen": base_var.imagen,
                    "stock_variante": base_var.stock_total - base_var.stock_reservado,
                    "marca": base_prod.marca,
                    "calidad_nivel": base_prod.calidad_nivel,
                }

    effective_occasion = args.occasion or "estilo atelier"
    has_any_anchor = bool(
        target_base_id
        or args.top_size or args.top_sizes
        or args.bottom_size or args.bottom_sizes
        or args.shoe_size or args.shoe_sizes
        or args.max_budget
        or args.occasion
    )
    if not has_any_anchor:
        return {
            "status": "needs_input",
            "missing_fields": ["occasion", "talla"],
            "instruction": "Pregunta por la ocasión, tallas o prenda base para armar el outfit personalizado.",
        }

    norm_gender = None
    if args.gender:
        g_val = normalized(args.gender)
        if any(k in g_val for k in ["hombre", "masculin", "varon", "chico", "caballero"]):
            norm_gender = "HOMBRE"
        elif any(k in g_val for k in ["mujer", "femenin", "dama", "chica"]):
            norm_gender = "MUJER"
        elif "unisex" in g_val:
            norm_gender = "UNISEX"

    all_available = search_products(context.db, only_available=True, limit=80)
    if norm_gender:
        candidates = [p for p in all_available if p.get("genero_objetivo") in (norm_gender, "UNISEX")]
    else:
        candidates = all_available
    if args.exclude_product_ids:
        excluded = set(args.exclude_product_ids)
        candidates = [p for p in candidates if p.get("id") not in excluded]
    if args.max_budget and not target_base_id:
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
            raw_top_sizes = args.top_sizes or ([args.top_size] if args.top_size else [])
            requested_sizes = [s for s in raw_top_sizes if not (s.isdigit() and int(s) > 36)]
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
        if not variant and product_variants:
            if not normalized_sizes:
                variant = product_variants[0]
            else:
                continue
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
    outerwear_acc = [p for p in enriched if any(k in normalized(p["nombre"]) for k in ["chamarra", "blazer", "chaqueta", "bomber", "cintur", "bolso", "reloj", "lentes", "bufanda"])]

    if base_item:
        b_name = normalized(base_item["nombre"])
        if any(k in b_name for k in ["polera", "camisa", "blusa", "polo", "hoodie"]):
            tops = [base_item] + [t for t in tops if t["id"] != base_item["id"]]
        elif any(k in b_name for k in ["jean", "pantalon", "jogger", "falda", "palazzo", "chino"]):
            bottoms = [base_item] + [b for b in bottoms if b["id"] != base_item["id"]]
        elif any(k in b_name for k in ["zapato", "zapatilla", "bota", "mocas", "chelsea", "oxford"]):
            footwear = [base_item] + [f for f in footwear if f["id"] != base_item["id"]]
        else:
            outerwear_acc = [base_item] + [a for a in outerwear_acc if a["id"] != base_item["id"]]

    restrictions = []
    if args.measurements:
        garment_measurements = {"pecho", "cintura", "cadera", "largo"}
        requested_garment_measurements = garment_measurements.intersection(args.measurements)
        if requested_garment_measurements:
            restrictions.append(
                "Tallas seleccionadas por equivalencia estándar con medidas ("
                + ", ".join(sorted(requested_garment_measurements))
                + ")"
            )
        if "pie" in args.measurements:
            restrictions.append("Calzado ajustado según estándar atelier")

    if args.top_type:
        norm_top = normalized(args.top_type)
        if not any(k in norm_top for k in ["calzado", "zapato", "zapatilla", "pantalon", "jean", "jogger", "falda"]):
            typed_tops = [p for p in tops if norm_top in normalized(p["nombre"])]
            if typed_tops:
                tops = typed_tops
            elif not base_item:
                restrictions.append(f"No hay {args.top_type} específico disponible; se seleccionó alternativa superior.")

    if args.bottom_type:
        norm_bottom = normalized(args.bottom_type)
        if not any(k in norm_bottom for k in ["polera", "camisa", "zapato", "calzado"]):
            typed_bottoms = [p for p in bottoms if norm_bottom in normalized(p["nombre"])]
            if typed_bottoms:
                bottoms = typed_bottoms
            elif not base_item:
                restrictions.append(f"No hay {args.bottom_type} específico disponible; se seleccionó alternativa inferior.")

    if args.bottom_fit:
        norm_fit = normalized(args.bottom_fit)
        if norm_fit not in ["l", "m", "s", "xl", "xxl", "xs", "40", "42", "44", "46", "38"]:
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
                        " ".join([
                            str(p.get("nombre") or ""),
                            str(p.get("descripcion") or ""),
                            str(p.get("descripcion_ai") or ""),
                            " ".join(p.get("tags_ai") or []),
                        ])
                    )
                    for term in fit_terms
                )
            ]
            if fitted_bottoms:
                bottoms = fitted_bottoms
            else:
                restrictions.append(f"Corte {args.bottom_fit} adaptado a disponibilidad del atelier.")

    # Fallbacks if strict size filtering yielded empty groups
    if not tops and all_available:
        cand_tops = [p for p in all_available if any(k in normalized(p["nombre"]) for k in ["polera", "camisa", "blusa", "polo", "hoodie"])]
        if norm_gender:
            cand_tops = [p for p in cand_tops if p.get("genero_objetivo") in (norm_gender, "UNISEX")]
        for cand in cand_tops:
            cand_vars = variants_by_product.get(cand["id"], [])
            if cand_vars:
                item = dict(cand)
                item.update({
                    "producto_id": cand["id"],
                    "variante_id": cand_vars[0].id,
                    "color": cand_vars[0].color,
                    "talla": cand_vars[0].talla,
                    "imagen": cand_vars[0].imagen,
                    "stock_variante": cand_vars[0].stock_total - cand_vars[0].stock_reservado,
                })
                tops.append(item)
                if len(tops) >= 3:
                    break

    if not bottoms and all_available:
        cand_bottoms = [p for p in all_available if any(k in normalized(p["nombre"]) for k in ["jean", "pantalon", "jogger", "falda", "palazzo", "chino"])]
        if norm_gender:
            cand_bottoms = [p for p in cand_bottoms if p.get("genero_objetivo") in (norm_gender, "UNISEX")]
        for cand in cand_bottoms:
            cand_vars = variants_by_product.get(cand["id"], [])
            if cand_vars:
                item = dict(cand)
                item.update({
                    "producto_id": cand["id"],
                    "variante_id": cand_vars[0].id,
                    "color": cand_vars[0].color,
                    "talla": cand_vars[0].talla,
                    "imagen": cand_vars[0].imagen,
                    "stock_variante": cand_vars[0].stock_total - cand_vars[0].stock_reservado,
                })
                bottoms.append(item)
                if len(bottoms) >= 3:
                    break

    if not footwear and all_available:
        cand_shoes = [p for p in all_available if any(k in normalized(p["nombre"]) for k in ["zapato", "zapatilla", "bota", "mocas", "chelsea", "oxford"])]
        if norm_gender:
            cand_shoes = [p for p in cand_shoes if p.get("genero_objetivo") in (norm_gender, "UNISEX")]
        for cand in cand_shoes:
            cand_vars = variants_by_product.get(cand["id"], [])
            if cand_vars:
                sorted_vars = sorted(cand_vars, key=lambda v: int(v.talla) if str(v.talla).isdigit() else 0, reverse=True)
                chosen_var = sorted_vars[0]
                item = dict(cand)
                item.update({
                    "producto_id": cand["id"],
                    "variante_id": chosen_var.id,
                    "color": chosen_var.color,
                    "talla": chosen_var.talla,
                    "imagen": chosen_var.imagen,
                    "stock_variante": chosen_var.stock_total - chosen_var.stock_reservado,
                })
                footwear.append(item)
                if args.shoe_size:
                    restrictions.append(f"Calzado seleccionado en talla {chosen_var.talla} (talla {args.shoe_size} agotada en catálogo)")
                if len(footwear) >= 3:
                    break

    top_sizes = args.top_sizes or ([args.top_size] if args.top_size else [])
    bottom_sizes = args.bottom_sizes or ([args.bottom_size] if args.bottom_size else [])
    shoe_sizes = args.shoe_sizes or ([args.shoe_size] if args.shoe_size else [])

    return {
        "ocasion": effective_occasion,
        "presupuesto_maximo": args.max_budget,
        "tops_sugeridos": tops[:4],
        "inferiores_sugeridos": bottoms[:4],
        "calzado_sugerido": footwear[:3],
        "complementos_abrigos": outerwear_acc[:4],
        "total_opciones": len(candidates),
        "base_product_id": target_base_id,
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


@dataclass
class ReadToolDefinition(ToolDefinition):
    """Explicit capability policy; new tools are denied unless classified."""
    read_only: bool = True


TOOLS = {
    tool.name: tool
    for tool in [
        ReadToolDefinition("get_my_favorites", "Consulta los favoritos reales del usuario para personalizar sugerencias.", EmptyArgs, _favorites),
        ReadToolDefinition("get_branch_availability", "Busca showrooms con stock exacto por prenda, talla y color, e indica dirección.", BranchAvailabilityArgs, _branch_availability),
        ReadToolDefinition("get_my_payment_status", "Lee el estado registrado del pago de un pedido propio; nunca aprueba pagos.", OrderPaymentArgs, _my_payment_status),
        ReadToolDefinition("calculate_selection_budget", "Calcula total exacto y saldo de una selección de variantes, una unidad por variante, sin cambiar el carrito.", SelectionBudgetArgs, _selection_budget),
        ReadToolDefinition(
            "search_products",
            "Busca prendas reales en el catálogo con filtros de nombre, categoría, presupuesto, color o talla.",
            SearchProductsArgs,
            _search,
        ),
        ReadToolDefinition(
            "get_product_detail",
            "Obtiene información detallada de una prenda: material, variantes, colores, tallas y stock.",
            ProductArgs,
            _product,
        ),
        ReadToolDefinition(
            "get_my_cart",
            "Lee todas las prendas que el usuario tiene actualmente en su perchero o carrito de compras (nombre, talla, color, precio y total). Usar siempre que el usuario pregunte por su perchero, carrito, bolsa, selección o qué tiene guardado.",
            EmptyArgs,
            _cart,
        ),
        ReadToolDefinition(
            "recommend_outfit",
            "Arma outfits completos armonizados (top + inferior + calzado + accesorios) según ocasión (cena, fiesta, casual, oficina) y presupuesto.",
            RecommendOutfitArgs,
            _recommend_outfit,
        ),
        ReadToolDefinition(
            "get_trending_pieces",
            "Obtiene las piezas más destacadas, de mayor calidad (Q5/Q4) y tendencia del atelier.",
            TrendingArgs,
            _trending,
        ),
        ReadToolDefinition(
            "get_new_arrivals",
            "Obtiene novedades del catálogo con stock y evita repetir recomendaciones recientes de la conversación.",
            NewArrivalsArgs,
            _new_arrivals,
        ),
        ReadToolDefinition(
            "get_most_expensive_product",
            "Devuelve exactamente una prenda: la de mayor precio con una variante disponible. No arma outfits.",
            EmptyArgs,
            _most_expensive,
        ),
        ReadToolDefinition(
            "get_stock",
            "Consulta stock real disponible por producto o variante.",
            StockArgs,
            _stock,
        ),
        ReadToolDefinition(
            "find_alternatives",
            "Busca alternativas con stock para ahorrar, mejorar calidad o mantener el mismo estilo.",
            AlternativesArgs,
            _alternatives,
        ),
        ReadToolDefinition(
            "calculate_cart_totals",
            "Calcula cantidades, subtotales y líneas exactas del carrito de compras.",
            EmptyArgs,
            _cart_totals,
        ),
        ReadToolDefinition(
            "compare_products",
            "Compara precio y calidad entre múltiples prendas de forma objetiva.",
            CompareProductsArgs,
            _compare,
        ),
        ReadToolDefinition(
            "get_my_orders",
            "Consulta los últimos pedidos y estados de compra del usuario autenticado.",
            EmptyArgs,
            _orders,
        ),
        ReadToolDefinition(
            "get_my_reservations",
            "Consulta reservas activas y fechas de vencimiento del usuario.",
            EmptyArgs,
            _reservations,
        ),
        ReadToolDefinition(
            "evaluate_garment_fit",
            "Calcula la holgura en cm, caída sastrera y tensión de una talla específica para el probador AR.",
            EvaluateGarmentFitArgs,
            _evaluate_fit,
        ),
    ]
}



def tool_catalog() -> list[dict]:
    return [tool.schema() for tool in TOOLS.values() if tool.read_only]


def execute_tool(name: str, arguments: dict, context: ToolContext) -> Any:
    tool = TOOLS.get(name)
    if not tool:
        return {"error": f"Tool no permitida: {name}"}
    if not tool.read_only:
        return {"error": "Esta operación requiere confirmación en la interfaz; no se ejecutó ningún cambio."}
    try:
        validated = tool.args_model.model_validate(arguments or {})
        return tool.handler(context, validated)
    except Exception as exc:
        return {"error": f"Error ejecutando {name}: {str(exc)}"}
