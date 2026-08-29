from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import (
    Address, Branch, BranchStaff, BranchStock, Cart, CartItem, InventoryMovement,
    Order, OrderItem, Payment, Product, ProductVariant, Reservation,
    ReservationItem, Role, User,
)


def variant_payload(variant: ProductVariant, product: Product) -> dict:
    return {
        "id": variant.id,
        "producto_id": product.id,
        "sku": variant.sku,
        "color": variant.color,
        "codigo_color": variant.codigo_color,
        "talla": variant.talla,
        "stock_total": variant.stock_total,
        "stock_reservado": variant.stock_reservado,
        "stock_disponible": variant.stock_total - variant.stock_reservado,
        "imagen": variant.imagen,
        "activo": variant.activo,
    }


def product_payload(product: Product, stock: int | None = None) -> dict:
    return {
        "id": product.id,
        "categoria_id": product.categoria_id,
        "nombre": product.nombre,
        "descripcion": product.descripcion,
        "marca": product.marca,
        "material": product.material,
        "precio": product.precio,
        "costo_referencia": product.costo_referencia,
        "calidad_nivel": product.calidad_nivel,
        "genero_objetivo": product.genero_objetivo,
        "descripcion_ai": product.descripcion_ai,
        "tags_ai": product.tags_ai,
        "imagenes": product.imagenes,
        "activo": product.activo,
        "stock_disponible": stock,
        "created_at": product.created_at,
    }


def _clean_search_tokens(query: str) -> list[str]:
    """Limpia y tokeniza la consulta en palabras clave significativas."""
    import re
    # Stopwords comunes en español y términos genéricos de consulta de moda
    stopwords = {
        "de", "del", "la", "las", "el", "los", "un", "una", "unos", "unas",
        "y", "e", "o", "u", "con", "sin", "para", "por", "en", "sobre", "a",
        "al", "que", "se", "me", "te", "mi", "tu", "su", "sus", "dime", "busca",
        "buscar", "mostrar", "muestra", "recomienda", "recomiendame", "recomendar",
        "quiero", "necesito", "tengo", "favor", "porfa", "ropa", "prenda", "prendas",
        "articulos", "articulo", "opcion", "opciones", "outfit", "conjunto", "estilo",
        "bs", "bob", "bolivianos", "pesos", "precio", "presupuesto", "maximo", "tope",
        "menos", "mayor", "menor", "mas", "que", "sea", "no", "algun", "alguna",
        "algunos", "algunas", "algo", "bonito", "bonita", "bonitos", "bonitas",
    }
    cleaned = re.sub(r"[^\w\s]", " ", query.lower())
    tokens = [t.strip() for t in cleaned.split() if len(t.strip()) > 1]
    filtered = [t for t in tokens if t not in stopwords and not t.isdigit()]
    return filtered if filtered else [t for t in tokens if not t.isdigit()]


def search_products(
    db: Session,
    query: str | None = None,
    category_id: int | None = None,
    min_price: Decimal | None = None,
    max_price: Decimal | None = None,
    gender: str | None = None,
    color: str | None = None,
    size: str | None = None,
    only_available: bool = True,
    offset: int = 0,
    limit: int = 20,
) -> list[dict]:
    import re
    # Intentar extraer tope de precio automáticamente si viene en el texto y no se envió explícito
    if query and max_price is None:
        price_match = re.search(r"(?:menor|menos|hasta|tope|presupuesto|max(?:imo)?|no mayor)\s*(?:a|de)?\s*(?:bs\.?|bob)?\s*(\d+(?:\.\d+)?)", query.lower())
        if price_match:
            try:
                max_price = Decimal(price_match.group(1))
            except Exception:
                pass

    stock = func.sum(ProductVariant.stock_total - ProductVariant.stock_reservado)
    
    def _build_base_stmt():
        stmt = (
            select(Product, stock.label("stock_disponible"))
            .join(ProductVariant, ProductVariant.producto_id == Product.id, isouter=True)
            .where(Product.activo.is_(True))
            .group_by(Product.id)
            .order_by(Product.created_at.desc())
        )
        if category_id:
            stmt = stmt.where(Product.categoria_id == category_id)
        if min_price is not None:
            stmt = stmt.where(Product.precio >= min_price)
        if max_price is not None:
            stmt = stmt.where(Product.precio <= max_price)
        if gender:
            stmt = stmt.where(Product.genero_objetivo == gender)
        if color:
            stmt = stmt.where(ProductVariant.color.ilike(f"%{color}%"))
        if size:
            stmt = stmt.where(ProductVariant.talla.ilike(size))
        if only_available:
            stmt = stmt.having(stock > 0)
        return stmt

    tokens = _clean_search_tokens(query) if query else []
    
    if tokens:
        # 1. Intentar coincidencia con TODAS las palabras clave (AND)
        and_conditions = []
        for tok in tokens:
            pat = f"%{tok}%"
            and_conditions.append(
                or_(
                    Product.nombre.ilike(pat),
                    Product.descripcion.ilike(pat),
                    Product.marca.ilike(pat),
                    Product.material.ilike(pat),
                    Product.descripcion_ai.ilike(pat),
                    func.array_to_string(Product.tags_ai, " ").ilike(pat),
                )
            )
        stmt_and = _build_base_stmt().where(*and_conditions)
        rows = db.execute(stmt_and.offset(offset).limit(limit)).all()
        if rows:
            return [product_payload(product, int(available or 0)) for product, available in rows]

        # 2. Si AND no dio resultados, buscar con CUALQUIERA de las palabras clave (OR)
        or_conditions = []
        for tok in tokens:
            pat = f"%{tok}%"
            or_conditions.append(Product.nombre.ilike(pat))
            or_conditions.append(Product.descripcion.ilike(pat))
            or_conditions.append(Product.marca.ilike(pat))
            or_conditions.append(Product.material.ilike(pat))
            or_conditions.append(Product.descripcion_ai.ilike(pat))
            or_conditions.append(func.array_to_string(Product.tags_ai, " ").ilike(pat))
        
        stmt_or = _build_base_stmt().where(or_(*or_conditions))
        rows = db.execute(stmt_or.offset(offset).limit(limit)).all()
        if rows:
            return [product_payload(product, int(available or 0)) for product, available in rows]

    # 3. Fallback: retornar catálogo disponible respetando filtros de categoría/precio/género
    stmt_fallback = _build_base_stmt()
    rows = db.execute(stmt_fallback.offset(offset).limit(limit)).all()
    return [product_payload(product, int(available or 0)) for product, available in rows]


def get_product_detail(db: Session, product_id: int, include_inactive: bool = False) -> dict:
    product = db.get(Product, product_id)
    if not product or (not include_inactive and not product.activo):
        raise HTTPException(404, "Producto no encontrado")
    variants = db.scalars(
        select(ProductVariant).where(ProductVariant.producto_id == product.id).order_by(
            ProductVariant.color, ProductVariant.talla
        )
    ).all()
    data = product_payload(product)
    data["variantes"] = [variant_payload(variant, product) for variant in variants]
    return data


def get_active_cart(db: Session, user_id: int, create: bool = True) -> Cart | None:
    cart = db.scalar(select(Cart).where(Cart.usuario_id == user_id, Cart.estado == "ACTIVO"))
    if not cart and create:
        cart = Cart(usuario_id=user_id, estado="ACTIVO")
        db.add(cart)
        db.flush()
    return cart


def cart_payload(db: Session, user_id: int) -> dict:
    cart = get_active_cart(db, user_id, create=False)
    if not cart:
        cart = Cart(usuario_id=user_id, estado="ACTIVO")
        db.add(cart)
        db.commit()
        db.refresh(cart)
    rows = db.execute(
        select(CartItem, ProductVariant, Product)
        .join(ProductVariant, ProductVariant.id == CartItem.variante_id)
        .join(Product, Product.id == ProductVariant.producto_id)
        .where(CartItem.carrito_id == cart.id)
        .order_by(CartItem.created_at)
    ).all()
    items = []
    subtotal = Decimal("0.00")
    total_items = 0
    for item, variant, product in rows:
        line_total = item.precio_referencia * item.cantidad
        subtotal += line_total
        total_items += item.cantidad
        items.append({
            "id": item.id, "variante_id": variant.id, "producto_id": product.id,
            "nombre": product.nombre, "sku": variant.sku, "color": variant.color,
            "talla": variant.talla, "cantidad": item.cantidad,
            "precio_unitario": item.precio_referencia, "subtotal": line_total,
            "stock_disponible": variant.stock_total - variant.stock_reservado,
            "imagen": variant.imagen or (product.imagenes[0] if product.imagenes else None),
        })
    return {"id": cart.id, "estado": cart.estado, "items": items, "total_items": total_items, "subtotal": subtotal}


def add_cart_item(db: Session, user_id: int, variant_id: int, quantity: int) -> dict:
    with db.begin_nested():
        variant = db.scalar(select(ProductVariant).where(ProductVariant.id == variant_id).with_for_update())
        if not variant or not variant.activo:
            raise HTTPException(404, "Variante no encontrada")
        product = db.get(Product, variant.producto_id)
        if not product or not product.activo:
            raise HTTPException(409, "El producto no esta disponible")
        cart = get_active_cart(db, user_id)
        item = db.scalar(select(CartItem).where(CartItem.carrito_id == cart.id, CartItem.variante_id == variant_id))
        desired = quantity + (item.cantidad if item else 0)
        if desired > variant.stock_total - variant.stock_reservado:
            raise HTTPException(409, "Stock insuficiente")
        if item:
            item.cantidad = desired
            item.precio_referencia = product.precio
        else:
            db.add(CartItem(carrito_id=cart.id, variante_id=variant.id, cantidad=quantity, precio_referencia=product.precio))
    db.commit()
    return cart_payload(db, user_id)


def add_cart_items_batch(
    db: Session,
    user_id: int,
    requested_items: list[tuple[int, int]],
) -> dict:
    requested: dict[int, int] = {}
    for variant_id, quantity in requested_items:
        requested[variant_id] = requested.get(variant_id, 0) + quantity

    with db.begin_nested():
        cart = get_active_cart(db, user_id)
        variants = db.scalars(
            select(ProductVariant)
            .where(ProductVariant.id.in_(requested))
            .with_for_update()
        ).all()
        variants_by_id = {variant.id: variant for variant in variants}
        if len(variants_by_id) != len(requested):
            raise HTTPException(404, "Una o más variantes del outfit no existen")

        existing_items = db.scalars(
            select(CartItem).where(
                CartItem.carrito_id == cart.id,
                CartItem.variante_id.in_(requested),
            )
        ).all()
        existing_by_variant = {item.variante_id: item for item in existing_items}

        for variant_id, quantity in requested.items():
            variant = variants_by_id[variant_id]
            product = db.get(Product, variant.producto_id)
            if not variant.activo or not product or not product.activo:
                raise HTTPException(409, "Una prenda del outfit ya no está disponible")
            existing = existing_by_variant.get(variant_id)
            desired = quantity + (existing.cantidad if existing else 0)
            available = variant.stock_total - variant.stock_reservado
            if desired > available:
                raise HTTPException(
                    409,
                    f"Stock insuficiente para {product.nombre}, talla {variant.talla}",
                )
            if existing:
                existing.cantidad = desired
                existing.precio_referencia = product.precio
            else:
                db.add(
                    CartItem(
                        carrito_id=cart.id,
                        variante_id=variant.id,
                        cantidad=quantity,
                        precio_referencia=product.precio,
                    )
                )
    db.commit()
    return cart_payload(db, user_id)


def replace_cart_items_batch(
    db: Session,
    user_id: int,
    requested_items: list[tuple[int, int]],
) -> dict:
    """Replace the whole active cart only after every requested variant is valid."""
    requested: dict[int, int] = {}
    for variant_id, quantity in requested_items:
        requested[variant_id] = requested.get(variant_id, 0) + quantity

    with db.begin_nested():
        cart = get_active_cart(db, user_id)
        variants = db.scalars(
            select(ProductVariant)
            .where(ProductVariant.id.in_(requested))
            .with_for_update()
        ).all()
        variants_by_id = {variant.id: variant for variant in variants}
        if len(variants_by_id) != len(requested):
            raise HTTPException(404, "Una o más variantes de la selección no existen")

        products_by_variant: dict[int, Product] = {}
        for variant_id, quantity in requested.items():
            variant = variants_by_id[variant_id]
            product = db.get(Product, variant.producto_id)
            if not variant.activo or not product or not product.activo:
                raise HTTPException(409, "Una prenda de la selección ya no está disponible")
            available = variant.stock_total - variant.stock_reservado
            if quantity > available:
                raise HTTPException(
                    409,
                    f"Stock insuficiente para {product.nombre}, talla {variant.talla}",
                )
            products_by_variant[variant_id] = product

        current_items = db.scalars(
            select(CartItem).where(CartItem.carrito_id == cart.id)
        ).all()
        for current_item in current_items:
            db.delete(current_item)
        db.flush()

        for variant_id, quantity in requested.items():
            db.add(
                CartItem(
                    carrito_id=cart.id,
                    variante_id=variant_id,
                    cantidad=quantity,
                    precio_referencia=products_by_variant[variant_id].precio,
                )
            )
    db.commit()
    return cart_payload(db, user_id)


def update_cart_item(db: Session, user_id: int, item_id: int, quantity: int) -> dict:
    cart = get_active_cart(db, user_id)
    item = db.scalar(select(CartItem).where(CartItem.id == item_id, CartItem.carrito_id == cart.id))
    if not item:
        raise HTTPException(404, "Item no encontrado")
    variant = db.scalar(select(ProductVariant).where(ProductVariant.id == item.variante_id).with_for_update())
    if quantity > variant.stock_total - variant.stock_reservado:
        raise HTTPException(409, "Stock insuficiente")
    item.cantidad = quantity
    db.commit()
    return cart_payload(db, user_id)


def delete_cart_item(db: Session, user_id: int, item_id: int) -> dict:
    cart = get_active_cart(db, user_id)
    item = db.scalar(select(CartItem).where(CartItem.id == item_id, CartItem.carrito_id == cart.id))
    if not item:
        raise HTTPException(404, "Item no encontrado")
    db.delete(item)
    db.commit()
    return cart_payload(db, user_id)


def replace_cart_item(db: Session, user_id: int, item_id: int, new_variant_id: int) -> dict:
    cart = get_active_cart(db, user_id)
    item = db.scalar(select(CartItem).where(CartItem.id == item_id, CartItem.carrito_id == cart.id))
    if not item:
        raise HTTPException(404, "Item no encontrado")
    variant = db.scalar(select(ProductVariant).where(ProductVariant.id == new_variant_id).with_for_update())
    if not variant or not variant.activo or item.cantidad > variant.stock_total - variant.stock_reservado:
        raise HTTPException(409, "La variante recomendada no tiene stock suficiente")
    product = db.get(Product, variant.producto_id)
    duplicate = db.scalar(select(CartItem).where(CartItem.carrito_id == cart.id, CartItem.variante_id == new_variant_id))
    if duplicate and duplicate.id != item.id:
        desired = duplicate.cantidad + item.cantidad
        if desired > variant.stock_total - variant.stock_reservado:
            raise HTTPException(409, "Stock insuficiente para combinar items")
        duplicate.cantidad = desired
        db.delete(item)
    else:
        item.variante_id = new_variant_id
        item.precio_referencia = product.precio
    db.commit()
    return cart_payload(db, user_id)


def _movement(variant: ProductVariant, movement_type: str, quantity: int, user_id: int | None, reference_type: str, reference_id: int) -> InventoryMovement:
    return InventoryMovement(
        variante_id=variant.id, tipo=movement_type, cantidad=quantity,
        stock_total_anterior=variant.stock_total,
        stock_total_nuevo=variant.stock_total,
        stock_reservado_anterior=variant.stock_reservado,
        stock_reservado_nuevo=variant.stock_reservado,
        referencia_tipo=reference_type, referencia_id=reference_id, usuario_id=user_id,
    )


def _sync_variant_inventory(db: Session, variant: ProductVariant) -> None:
    totals = db.execute(
        select(
            func.coalesce(func.sum(BranchStock.stock_total), 0),
            func.coalesce(func.sum(BranchStock.stock_reservado), 0),
        ).where(BranchStock.variante_id == variant.id, BranchStock.activo.is_(True))
    ).one()
    variant.stock_total = int(totals[0])
    variant.stock_reservado = int(totals[1])


def _resolve_branch(db: Session, branch_id: int | None) -> Branch:
    if branch_id is not None:
        branch = db.scalar(select(Branch).where(Branch.id == branch_id, Branch.activo.is_(True)))
    else:
        branch = db.scalar(select(Branch).where(Branch.activo.is_(True)).order_by(Branch.id))
    if not branch:
        raise HTTPException(409, "No existe una sucursal activa para realizar la reserva")
    return branch


def staff_can_access_branch(db: Session, user: User, branch_id: int | None) -> bool:
    if user.rol == Role.ADMIN:
        return True
    if branch_id is None:
        return False
    return db.scalar(
        select(BranchStaff.id).where(
            BranchStaff.usuario_id == user.id,
            BranchStaff.sucursal_id == branch_id,
            BranchStaff.activo.is_(True),
        )
    ) is not None


def create_reservation_from_cart(
    db: Session,
    user_id: int,
    observation: str | None,
    branch_id: int | None = None,
    requested_items: list[tuple[int, int]] | None = None,
) -> Reservation:
    expire_due_reservations(db)
    branch = _resolve_branch(db, branch_id)
    cart = None
    source_items: list[tuple[int, int, Decimal]] = []
    if requested_items:
        for variant_id, quantity in requested_items:
            variant = db.get(ProductVariant, variant_id)
            product = db.get(Product, variant.producto_id) if variant else None
            if not variant or not variant.activo or not product or not product.activo:
                raise HTTPException(404, f"Variante {variant_id} no disponible")
            source_items.append((variant.id, quantity, product.precio))
    else:
        cart = get_active_cart(db, user_id, create=False)
        if cart:
            cart_items = db.scalars(select(CartItem).where(CartItem.carrito_id == cart.id)).all()
            source_items = [
                (item.variante_id, item.cantidad, item.precio_referencia)
                for item in cart_items
            ]
    if not source_items:
        raise HTTPException(409, "Debe enviar prendas o tener productos en el carrito")
    reservation = Reservation(
        usuario_id=user_id,
        sucursal_id=branch.id,
        vence_at=datetime.now(timezone.utc) + timedelta(minutes=settings.RESERVATION_TTL_MINUTES),
        observacion=observation,
    )
    db.add(reservation)
    db.flush()
    for variant_id, quantity, reference_price in source_items:
        variant = db.scalar(select(ProductVariant).where(ProductVariant.id == variant_id).with_for_update())
        branch_stock = db.scalar(
            select(BranchStock).where(
                BranchStock.sucursal_id == branch.id,
                BranchStock.variante_id == variant_id,
                BranchStock.activo.is_(True),
            ).with_for_update()
        )
        if not branch_stock:
            db.rollback()
            raise HTTPException(409, f"La variante {variant.sku} no está disponible en {branch.nombre}")
        available = branch_stock.stock_total - branch_stock.stock_reservado
        if quantity > available:
            db.rollback()
            raise HTTPException(409, f"Stock insuficiente para {variant.sku} en {branch.nombre}")
        previous_reserved = variant.stock_reservado
        branch_stock.stock_reservado += quantity
        _sync_variant_inventory(db, variant)
        movement = _movement(variant, "RESERVA", quantity, user_id, "RESERVA", reservation.id)
        movement.sucursal_id = branch.id
        movement.stock_reservado_anterior = previous_reserved
        db.add(movement)
        db.add(ReservationItem(
            reserva_id=reservation.id, variante_id=variant.id,
            cantidad=quantity, precio_referencia=reference_price,
        ))
    if cart:
        cart.estado = "CONVERTIDO"
    db.commit()
    db.refresh(reservation)
    return reservation


def cancel_reservation(db: Session, reservation: Reservation, actor_id: int) -> Reservation:
    if reservation.estado not in {"PENDIENTE", "CONFIRMADA", "EN_PREPARACION", "LISTA"}:
        raise HTTPException(409, "La reserva ya no se puede cancelar")
    items = db.scalars(select(ReservationItem).where(ReservationItem.reserva_id == reservation.id)).all()
    for item in items:
        variant = db.scalar(select(ProductVariant).where(ProductVariant.id == item.variante_id).with_for_update())
        previous_reserved = variant.stock_reservado
        branch_stock = None
        if reservation.sucursal_id is not None:
            branch_stock = db.scalar(
                select(BranchStock).where(
                    BranchStock.sucursal_id == reservation.sucursal_id,
                    BranchStock.variante_id == item.variante_id,
                ).with_for_update()
            )
        if branch_stock:
            branch_stock.stock_reservado = max(0, branch_stock.stock_reservado - item.cantidad)
            _sync_variant_inventory(db, variant)
        else:
            variant.stock_reservado = max(0, variant.stock_reservado - item.cantidad)
        movement = _movement(variant, "LIBERACION_RESERVA", -item.cantidad, actor_id, "RESERVA", reservation.id)
        movement.sucursal_id = reservation.sucursal_id
        movement.stock_reservado_anterior = previous_reserved
        db.add(movement)
    reservation.estado = "CANCELADA"
    db.commit()
    db.refresh(reservation)
    return reservation


def expire_due_reservations(db: Session, limit: int = 100) -> int:
    """Libera reservas vencidas. Seguro para varios workers con SKIP LOCKED."""
    due = db.scalars(
        select(Reservation)
        .where(
            Reservation.estado.in_(["PENDIENTE", "CONFIRMADA", "EN_PREPARACION", "LISTA"]),
            Reservation.vence_at <= datetime.now(timezone.utc),
        )
        .order_by(Reservation.vence_at)
        .limit(limit)
        .with_for_update(skip_locked=True)
    ).all()
    for reservation in due:
        items = db.scalars(
            select(ReservationItem).where(ReservationItem.reserva_id == reservation.id)
        ).all()
        for item in items:
            variant = db.scalar(
                select(ProductVariant).where(ProductVariant.id == item.variante_id).with_for_update()
            )
            previous_reserved = variant.stock_reservado
            branch_stock = None
            if reservation.sucursal_id is not None:
                branch_stock = db.scalar(
                    select(BranchStock).where(
                        BranchStock.sucursal_id == reservation.sucursal_id,
                        BranchStock.variante_id == item.variante_id,
                    ).with_for_update()
                )
            if branch_stock:
                branch_stock.stock_reservado = max(0, branch_stock.stock_reservado - item.cantidad)
                _sync_variant_inventory(db, variant)
            else:
                variant.stock_reservado = max(0, variant.stock_reservado - item.cantidad)
            movement = _movement(
                variant, "LIBERACION_RESERVA", -item.cantidad,
                reservation.usuario_id, "RESERVA", reservation.id,
            )
            movement.stock_reservado_anterior = previous_reserved
            movement.sucursal_id = reservation.sucursal_id
            movement.observacion = "Liberacion automatica por vencimiento"
            db.add(movement)
        reservation.estado = "VENCIDA"
    db.commit()
    return len(due)


def checkout_cart(db: Session, user: User, delivery_type: str, address_id: int | None, shipping: Decimal, observation: str | None) -> Order:
    cart = get_active_cart(db, user.id, create=False)
    items = db.scalars(select(CartItem).where(CartItem.carrito_id == cart.id if cart else -1)).all()
    if not items:
        raise HTTPException(409, "El carrito esta vacio")
    address_snapshot = {}
    if delivery_type == "DELIVERY":
        address = db.scalar(select(Address).where(Address.id == address_id, Address.usuario_id == user.id))
        if not address:
            raise HTTPException(404, "Direccion no encontrada")
        address_snapshot = {
            "alias": address.alias, "departamento": address.departamento, "ciudad": address.ciudad,
            "zona": address.zona, "direccion": address.direccion, "referencia": address.referencia,
            "telefono_contacto": address.telefono_contacto,
        }
    subtotal = sum((item.precio_referencia * item.cantidad for item in items), Decimal("0.00"))
    order = Order(
        usuario_id=user.id, estado="PENDIENTE_PAGO", canal="MOBILE", tipo_entrega=delivery_type,
        subtotal=subtotal, descuento=0, costo_envio=shipping, total=subtotal + shipping,
        direccion_entrega_snapshot=address_snapshot, observacion=observation,
    )
    db.add(order)
    db.flush()
    for item in items:
        variant = db.scalar(select(ProductVariant).where(ProductVariant.id == item.variante_id).with_for_update())
        product = db.get(Product, variant.producto_id)
        available = variant.stock_total - variant.stock_reservado
        if item.cantidad > available:
            db.rollback()
            raise HTTPException(409, f"Stock insuficiente para {variant.sku}")
        previous_total = variant.stock_total
        variant.stock_total -= item.cantidad
        movement = _movement(variant, "VENTA", -item.cantidad, user.id, "PEDIDO", order.id)
        movement.stock_total_anterior = previous_total
        db.add(movement)
        db.add(OrderItem(
            pedido_id=order.id, producto_id=product.id, variante_id=variant.id,
            nombre_snapshot=product.nombre, sku_snapshot=variant.sku,
            color_snapshot=variant.color, talla_snapshot=variant.talla,
            cantidad=item.cantidad, precio_unitario=item.precio_referencia,
            descuento=0, subtotal=item.precio_referencia * item.cantidad,
        ))
    cart.estado = "CONVERTIDO"
    db.commit()
    db.refresh(order)
    return order


def convert_reservation_to_order(db: Session, reservation: Reservation, actor_id: int) -> Order:
    if reservation.estado not in {"CONFIRMADA", "EN_PREPARACION", "LISTA", "RETIRADA"}:
        raise HTTPException(409, "La reserva no se puede convertir")
    items = db.scalars(select(ReservationItem).where(ReservationItem.reserva_id == reservation.id)).all()
    subtotal = sum((item.precio_referencia * item.cantidad for item in items), Decimal("0.00"))
    order = Order(
        usuario_id=reservation.usuario_id, reserva_id=reservation.id,
        sucursal_id=reservation.sucursal_id, estado="PENDIENTE_PAGO",
        canal="TIENDA", tipo_entrega="TIENDA", subtotal=subtotal, descuento=0,
        costo_envio=0, total=subtotal,
    )
    db.add(order)
    db.flush()
    for item in items:
        variant = db.scalar(select(ProductVariant).where(ProductVariant.id == item.variante_id).with_for_update())
        product = db.get(Product, variant.producto_id)
        branch_stock = None
        if reservation.sucursal_id is not None:
            branch_stock = db.scalar(
                select(BranchStock).where(
                    BranchStock.sucursal_id == reservation.sucursal_id,
                    BranchStock.variante_id == item.variante_id,
                ).with_for_update()
            )
        reserved = branch_stock.stock_reservado if branch_stock else variant.stock_reservado
        total = branch_stock.stock_total if branch_stock else variant.stock_total
        if reserved < item.cantidad or total < item.cantidad:
            db.rollback()
            raise HTTPException(409, f"Stock reservado inconsistente para {variant.sku}")
        previous_total, previous_reserved = variant.stock_total, variant.stock_reservado
        if branch_stock:
            branch_stock.stock_total -= item.cantidad
            branch_stock.stock_reservado -= item.cantidad
            _sync_variant_inventory(db, variant)
        else:
            variant.stock_total -= item.cantidad
            variant.stock_reservado -= item.cantidad
        movement = _movement(variant, "VENTA", -item.cantidad, actor_id, "PEDIDO", order.id)
        movement.sucursal_id = reservation.sucursal_id
        movement.stock_total_anterior = previous_total
        movement.stock_reservado_anterior = previous_reserved
        db.add(movement)
        db.add(OrderItem(
            pedido_id=order.id, producto_id=product.id, variante_id=variant.id,
            nombre_snapshot=product.nombre, sku_snapshot=variant.sku,
            color_snapshot=variant.color, talla_snapshot=variant.talla,
            cantidad=item.cantidad, precio_unitario=item.precio_referencia,
            descuento=0, subtotal=item.precio_referencia * item.cantidad,
        ))
    reservation.estado = "CONVERTIDA"
    reservation.atendido_por_id = actor_id
    reservation.atendido_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(order)
    return order


def create_payment(
    db: Session, order: Order, method: str, idempotency_key: str | None = None
) -> Payment:
    if order.estado != "PENDIENTE_PAGO":
        raise HTTPException(409, "El pedido no esta pendiente de pago")
    if idempotency_key:
        existing = db.scalar(
            select(Payment).where(Payment.idempotency_key == idempotency_key)
        )
        if existing:
            if existing.pedido_id != order.id or existing.metodo != method:
                raise HTTPException(409, "Idempotency-Key ya fue usada con otra operación")
            return existing
    reference = f"DM-{order.id}-{uuid4().hex[:12]}"
    payment = Payment(
        pedido_id=order.id, metodo=method,
        proveedor="MOCK" if settings.PAYMENT_PROVIDER == "mock" else "EXTERNAL",
        monto=order.total, moneda="BOB", estado="PENDIENTE",
        referencia_externa=reference,
        idempotency_key=idempotency_key,
        qr_payload=f"drapemind://pay/{reference}" if method == "QR" else None,
    )
    db.add(payment)
    db.commit()
    db.refresh(payment)
    return payment


def confirm_payment(db: Session, reference: str, new_status: str) -> Payment:
    payment = db.scalar(select(Payment).where(Payment.referencia_externa == reference).with_for_update())
    if not payment:
        raise HTTPException(404, "Pago no encontrado")
    if payment.estado in {"APROBADO", "RECHAZADO"}:
        return payment
    payment.estado = new_status
    order = db.scalar(select(Order).where(Order.id == payment.pedido_id).with_for_update())
    if new_status == "APROBADO":
        now = datetime.now(timezone.utc)
        payment.paid_at = now
        order.estado = "PAGADO"
        order.paid_at = now
    db.commit()
    db.refresh(payment)
    return payment


def cancel_unpaid_order(db: Session, order: Order, actor_id: int) -> Order:
    """Compensa el stock descontado en checkout si el pedido aun no fue pagado."""
    if order.estado != "PENDIENTE_PAGO":
        raise HTTPException(409, "Solo se puede cancelar aqui un pedido pendiente de pago")
    items = db.scalars(select(OrderItem).where(OrderItem.pedido_id == order.id)).all()
    for item in items:
        if item.variante_id is None:
            continue
        variant = db.scalar(
            select(ProductVariant).where(ProductVariant.id == item.variante_id).with_for_update()
        )
        if not variant:
            continue
        previous_total = variant.stock_total
        variant.stock_total += item.cantidad
        movement = _movement(
            variant, "DEVOLUCION", item.cantidad, actor_id, "PEDIDO", order.id
        )
        movement.stock_total_anterior = previous_total
        movement.observacion = "Reposicion por cancelacion antes del pago"
        db.add(movement)
    order.estado = "CANCELADO"
    order.cancelled_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(order)
    return order
