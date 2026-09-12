"""
DrapeMind - Módulo de Seeding Integral y Catálogo Población
=========================================================
Carga:
1. Sedes y Ciudades (Santa Cruz Central, Norte, La Paz Sopocachi).
2. Usuarios para todos los roles (Admin, Encargado, Vendedor, Cajero, Cliente),
   asignación a sucursales (BranchStaff), direcciones y perfil de estilo IA.
3. Catálogo completo desde CSVs de población (67 categorías, 887 productos, 4,296 variantes),
   con tags de IA, imágenes JSONB, precios y resolución de jerarquías.
4. Distribución de inventario por sucursal (BranchStock) garantizando stock activo.
5. Datos de prueba operativos (reservas activas con QR para tienda, pedidos con comprobante emitido).
6. Reseteo de secuencias PostgreSQL (setval).
"""

from __future__ import annotations

import csv
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
from pathlib import Path
import sys
from typing import Any, Callable
import uuid

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

BACKEND_DIR = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy import delete, func, select, text
from app.core.security import hash_password
from app.db.session import SessionLocal
from app.models.entities import (
    Address, Branch, BranchStaff, BranchStock, Category, City, Gender, Order,
    OrderItem, Payment, Product, ProductVariant, Reservation, ReservationItem,
    Role, User, UserStatus, UserStyleProfile,
)

DATA_DIR = Path(__file__).resolve().parent / "data"
SEED_PREFIX = "seed:poblacion:"


def parse_pg_text_array(value: str) -> list[str]:
    """Convierte cadenas estilo PostgreSQL '{foo,bar}' a lista Python."""
    val = (value or "").strip()
    if not val or val == "{}":
        return []
    if val.startswith("{") and val.endswith("}"):
        inner = val[1:-1]
        if not inner:
            return []
        reader = csv.reader([inner], delimiter=",", quotechar='"', escapechar="\\")
        return [item.strip() for item in next(reader) if item.strip()]
    return [val]


def parse_json_array(value: str) -> list[str]:
    """Parsea un arreglo JSON de strings."""
    if not value:
        return []
    try:
        res = json.loads(value)
        return res if isinstance(res, list) else [str(res)]
    except Exception:
        return []


def seed_cities_and_branches(db, log_fn: Callable[[str], None] = print) -> tuple[Branch, Branch]:
    """Crea ciudades principales y sucursales (Showrooms) de DrapeMind."""
    # 1. Santa Cruz
    scz_city = db.scalar(
        select(City).where(
            City.nombre == "Santa Cruz de la Sierra",
            City.departamento == "Santa Cruz",
        )
    )
    if not scz_city:
        scz_city = City(nombre="Santa Cruz de la Sierra", departamento="Santa Cruz", activo=True)
        db.add(scz_city)
        db.flush()

    # 2. La Paz
    lpz_city = db.scalar(
        select(City).where(
            City.nombre == "La Paz",
            City.departamento == "La Paz",
        )
    )
    if not lpz_city:
        lpz_city = City(nombre="La Paz", departamento="La Paz", activo=True)
        db.add(lpz_city)
        db.flush()

    branch_specs = [
        ("SCZ-CENTRAL", "DrapeMind Showroom Central", "Av. San Martín #450, Equipetrol, Santa Cruz", "70011221", scz_city.id),
        ("SCZ-NORTE", "DrapeMind Showroom Norte", "Av. Banzer esq. 4to Anillo, Santa Cruz", "70011222", scz_city.id),
        ("LPZ-SOPOCACHI", "DrapeMind Atelier La Paz", "Av. 20 de Octubre #2100, Sopocachi, La Paz", "70011223", lpz_city.id),
    ]

    branches: list[Branch] = []
    for code, name, address, phone, city_id in branch_specs:
        b = db.scalar(select(Branch).where(Branch.codigo == code))
        if not b:
            b = Branch(
                ciudad_id=city_id,
                codigo=code,
                nombre=name,
                direccion=address,
                telefono=phone,
                activo=True,
            )
            db.add(b)
            db.flush()
            log_fn(f"  + Sucursal creada: {name} [{code}]")
        else:
            b.nombre = name
            b.direccion = address
            b.telefono = phone
            b.activo = True
            log_fn(f"  = Sucursal verificada: {name} [{code}]")
        branches.append(b)

    return branches[0], branches[1]


def seed_users(db, central_branch: Branch, north_branch: Branch, log_fn: Callable[[str], None] = print) -> dict[str, User]:
    """Crea cuentas completas para todos los roles con credenciales y direcciones."""
    users_data = [
        # Administradores
        {
            "nombre": "Admin DrapeMind",
            "email": "admin@drapemind.com",
            "password": "Admin12345!",
            "rol": Role.ADMIN,
            "telefono": "70011223",
            "direccion": "Calle 21 de Calacoto #1200, La Paz",
            "branch": None,
        },
        {
            "nombre": "German Rojas (SuperAdmin)",
            "email": "rojascruzgermanlino@gmail.com",
            "password": "Password123!",
            "rol": Role.ADMIN,
            "telefono": "63014529",
            "direccion": "Av. Las Américas #780, Equipetrol, Santa Cruz",
            "branch": None,
        },
        # Encargados de Tienda (Store Managers)
        {
            "nombre": "Elena Encargada Central",
            "email": "encargado@drapemind.com",
            "password": "Encargado12345!",
            "rol": Role.ENCARGADO,
            "telefono": "73344556",
            "direccion": "Av. San Martín #450, Equipetrol, Santa Cruz",
            "branch": central_branch,
        },
        {
            "nombre": "Roberto Encargado Norte",
            "email": "encargado.norte@drapemind.com",
            "password": "Encargado12345!",
            "rol": Role.ENCARGADO,
            "telefono": "73344557",
            "direccion": "Av. Banzer esq. 4to Anillo, Santa Cruz",
            "branch": north_branch,
        },
        # Vendedores (Sales Representatives)
        {
            "nombre": "Carlos Vendedor Central",
            "email": "vendedor@drapemind.com",
            "password": "Vendedor12345!",
            "rol": Role.VENDEDOR,
            "telefono": "71122334",
            "direccion": "Calle Rene Moreno #120, Santa Cruz",
            "branch": central_branch,
        },
        {
            "nombre": "Lucia Vendedora Norte",
            "email": "vendedora@drapemind.com",
            "password": "Vendedor12345!",
            "rol": Role.VENDEDOR,
            "telefono": "71122335",
            "direccion": "Av. Cristo Redentor #300, Santa Cruz",
            "branch": north_branch,
        },
        # Cajeros (Cashiers)
        {
            "nombre": "Mateo Cajero Central",
            "email": "cajero@drapemind.com",
            "password": "Cajero12345!",
            "rol": Role.CAJERO,
            "telefono": "74455667",
            "direccion": "Av. Monseñor Rivero #500, Santa Cruz",
            "branch": central_branch,
        },
        {
            "nombre": "Valeria Cajera Norte",
            "email": "cajera@drapemind.com",
            "password": "Cajero12345!",
            "rol": Role.CAJERO,
            "telefono": "74455668",
            "direccion": "Av. Beni #800, Santa Cruz",
            "branch": north_branch,
        },
        # Clientes
        {
            "nombre": "Maria Cliente VIP",
            "email": "cliente@drapemind.com",
            "password": "Cliente12345!",
            "rol": Role.CLIENTE,
            "telefono": "72233445",
            "direccion": "Av. Las Palmas #230, Santa Cruz",
            "branch": None,
        },
        {
            "nombre": "Sofia Montes (Cliente Frecuente)",
            "email": "sofia.montes@gmail.com",
            "password": "Cliente12345!",
            "rol": Role.CLIENTE,
            "telefono": "76655443",
            "direccion": "Calle 9 de Calacoto #45, La Paz",
            "branch": None,
        },
        {
            "nombre": "Lucas Paredes (Cliente Casual)",
            "email": "lucas.paredes@gmail.com",
            "password": "Cliente12345!",
            "rol": Role.CLIENTE,
            "telefono": "78899001",
            "direccion": "Av. Ballivián #340, Cochabamba",
            "branch": None,
        },
    ]

    user_map: dict[str, User] = {}
    for udata in users_data:
        email = udata["email"].lower()
        user = db.scalar(select(User).where(func.lower(User.email) == email))
        if not user:
            user = User(
                nombre=udata["nombre"],
                email=email,
                password_hash=hash_password(udata["password"]),
                rol=udata["rol"],
                estado=UserStatus.ACTIVO,
                telefono=udata["telefono"],
            )
            db.add(user)
            db.flush()
            log_fn(f"  + Usuario creado: {email} [{udata['rol'].value}] (Pass: {udata['password']})")
        else:
            user.nombre = udata["nombre"]
            user.rol = udata["rol"]
            user.estado = UserStatus.ACTIVO
            user.password_hash = hash_password(udata["password"])
            db.flush()
            log_fn(f"  = Usuario sincronizado: {email} [{udata['rol'].value}]")

        user_map[email] = user

        # 1. Dirección principal
        addr = db.scalar(select(Address).where(Address.usuario_id == user.id))
        if not addr:
            addr = Address(
                usuario_id=user.id,
                alias="Dirección Principal",
                departamento="Santa Cruz",
                ciudad="Santa Cruz de la Sierra",
                zona="Equipetrol / Centro",
                direccion=udata["direccion"],
                telefono_contacto=udata["telefono"],
                es_principal=True,
            )
            db.add(addr)
            db.flush()

        # 2. Asignación a sucursal si es personal operativo
        target_branch = udata.get("branch")
        if target_branch:
            staff_rel = db.scalar(
                select(BranchStaff).where(
                    BranchStaff.usuario_id == user.id,
                    BranchStaff.sucursal_id == target_branch.id,
                )
            )
            if not staff_rel:
                db.add(BranchStaff(usuario_id=user.id, sucursal_id=target_branch.id, activo=True))
                db.flush()
                log_fn(f"    - Asignado a sucursal: {target_branch.nombre}")

    # 3. Perfil de estilo IA para cliente principal
    vip_client = user_map.get("cliente@drapemind.com")
    if vip_client:
        style = db.scalar(select(UserStyleProfile).where(UserStyleProfile.usuario_id == vip_client.id))
        if not style:
            style = UserStyleProfile(
                usuario_id=vip_client.id,
                genero="FEMENINO",
                estilos_preferidos=["Casual Elegante", "Minimalista"],
                colores_favoritos=["Negro", "Azul Marino", "Blanco", "Beige"],
                ocasiones_frecuentes=["Cena", "Trabajo", "Fin de semana"],
                talla_superior="M",
                talla_inferior="30",
                talla_calzado="38",
                presupuesto_habitual=Decimal("500.00"),
                silueta_preferida="Regular / Relajada",
                adn_estilo_ia="Preferencia por tejidos naturales de algodón y lino para clima cálido.",
                completado=True,
            )
            db.add(style)
            db.flush()

    return user_map


def seed_categories_from_csv(db, log_fn: Callable[[str], None] = print) -> dict[int, int]:
    """Carga categorías desde data/categorias.csv resolviendo la jerarquía padre-hijo."""
    csv_file = DATA_DIR / "categorias.csv"
    if not csv_file.exists():
        log_fn("  ! No se encontró categorias.csv en data/; saltando carga de categorías.")
        return {}

    with csv_file.open("r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))

    log_fn(f"  → Cargando {len(rows)} categorías desde {csv_file.name}...")

    rows_by_id = {int(r["id"].strip()): r for r in rows if r.get("id")}
    category_id_map: dict[int, int] = {}
    pending = set(rows_by_id.keys())

    while pending:
        progress = False
        for cid in list(pending):
            r = rows_by_id[cid]
            parent_raw = (r.get("parent_id") or "").strip()
            parent_cid = int(parent_raw) if parent_raw and parent_raw.isdigit() else None

            # Si tiene padre pero aún no ha sido insertado, esperar
            if parent_cid is not None and parent_cid not in category_id_map:
                continue

            parent_db_id = category_id_map.get(parent_cid) if parent_cid is not None else None
            slug = r["slug"].strip()

            existing = db.scalar(select(Category).where(Category.slug == slug))
            if not existing:
                cat = Category(
                    nombre=r["nombre"].strip(),
                    slug=slug,
                    descripcion=r.get("descripcion", "").strip() or None,
                    parent_id=parent_db_id,
                    activo=r.get("activo", "true").lower() in {"true", "1", "t"},
                )
                db.add(cat)
                db.flush()
                category_id_map[cid] = cat.id
            else:
                existing.nombre = r["nombre"].strip()
                existing.descripcion = r.get("descripcion", "").strip() or None
                existing.parent_id = parent_db_id
                existing.activo = True
                db.flush()
                category_id_map[cid] = existing.id

            pending.remove(cid)
            progress = True

        if not progress and pending:
            # En caso de ciclo o error en parent_id, insertar los restantes como raíz
            for cid in list(pending):
                r = rows_by_id[cid]
                slug = r["slug"].strip()
                existing = db.scalar(select(Category).where(Category.slug == slug))
                if not existing:
                    cat = Category(
                        nombre=r["nombre"].strip(),
                        slug=slug,
                        descripcion=r.get("descripcion", "").strip() or None,
                        parent_id=None,
                        activo=True,
                    )
                    db.add(cat)
                    db.flush()
                    category_id_map[cid] = cat.id
                else:
                    category_id_map[cid] = existing.id
            break

    log_fn(f"  ✓ {len(category_id_map)} categorías sincronizadas correctamente.")
    return category_id_map


def seed_products_from_csv(db, category_id_map: dict[int, int], log_fn: Callable[[str], None] = print) -> dict[int, int]:
    """Carga productos desde data/productos.csv con tags IA, precios e imágenes JSONB."""
    csv_file = DATA_DIR / "productos.csv"
    if not csv_file.exists():
        log_fn("  ! No se encontró productos.csv en data/; saltando productos.")
        return {}

    with csv_file.open("r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))

    log_fn(f"  → Cargando {len(rows)} productos desde {csv_file.name}...")
    product_id_map: dict[int, int] = {}

    # Si no había mapa de categorías (p.ej. ya estaban creadas), obtener por slug
    all_cats = {c.id: c.id for c in db.scalars(select(Category))}
    first_cat_id = next(iter(all_cats.keys()), 1)

    for idx, r in enumerate(rows, start=1):
        source_id = int(r["id"].strip())
        source_cat_id = int(r["categoria_id"].strip()) if r.get("categoria_id") else first_cat_id
        db_cat_id = category_id_map.get(source_cat_id, source_cat_id)
        if db_cat_id not in all_cats:
            db_cat_id = first_cat_id

        marker = f"{SEED_PREFIX}{source_id}"
        tags = parse_pg_text_array(r.get("tags_ai", ""))
        if marker not in tags:
            tags.append(marker)

        images = parse_json_array(r.get("imagenes", ""))
        price = Decimal(r.get("precio", "150.00").strip() or "150.00")
        cost = Decimal(r.get("costo_referencia", "60.00").strip() or "60.00") if r.get("costo_referencia") else None
        calidad = int(r.get("calidad_nivel", "4").strip() or "4")
        calidad = max(1, min(5, calidad))

        genero_raw = (r.get("genero_objetivo") or "UNISEX").strip().upper()
        if genero_raw not in {g.value for g in Gender}:
            genero_raw = "UNISEX"

        # Buscar por marcador o por ID explícito
        prod = db.scalar(
            select(Product).where(
                Product.tags_ai.contains([marker])
            )
        )
        if not prod:
            prod = Product(
                categoria_id=db_cat_id,
                nombre=r["nombre"].strip(),
                descripcion=r.get("descripcion", "").strip() or None,
                marca=r.get("marca", "").strip() or None,
                material=r.get("material", "").strip() or None,
                precio=price,
                costo_referencia=cost,
                calidad_nivel=calidad,
                genero_objetivo=Gender(genero_raw),
                descripcion_ai=r.get("descripcion_ai", "").strip() or None,
                tags_ai=tags,
                imagenes=images,
                activo=r.get("activo", "true").lower() in {"true", "1", "t"},
            )
            db.add(prod)
            db.flush()
        else:
            prod.categoria_id = db_cat_id
            prod.nombre = r["nombre"].strip()
            prod.descripcion = r.get("descripcion", "").strip() or None
            prod.marca = r.get("marca", "").strip() or None
            prod.material = r.get("material", "").strip() or None
            prod.precio = price
            prod.costo_referencia = cost
            prod.calidad_nivel = calidad
            prod.genero_objetivo = Gender(genero_raw)
            prod.descripcion_ai = r.get("descripcion_ai", "").strip() or None
            prod.tags_ai = tags
            prod.imagenes = images
            prod.activo = True
            db.flush()

        product_id_map[source_id] = prod.id
        if idx % 200 == 0 or idx == len(rows):
            log_fn(f"    - Procesados {idx}/{len(rows)} productos...")

    log_fn(f"  ✓ {len(product_id_map)} productos sincronizados con éxito.")
    return product_id_map


def seed_variants_from_csv(db, product_id_map: dict[int, int], log_fn: Callable[[str], None] = print) -> int:
    """Carga variantes desde data/variantes_producto.csv con SKUs únicos y colores."""
    csv_file = DATA_DIR / "variantes_producto.csv"
    if not csv_file.exists():
        log_fn("  ! No se encontró variantes_producto.csv en data/; saltando variantes.")
        return 0

    with csv_file.open("r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))

    log_fn(f"  → Cargando {len(rows)} variantes desde {csv_file.name}...")
    inserted = 0

    for idx, r in enumerate(rows, start=1):
        source_prod_id = int(r["producto_id"].strip())
        db_prod_id = product_id_map.get(source_prod_id)
        if not db_prod_id:
            continue

        sku = r["sku"].strip()
        stock_total = int(r.get("stock_total", "15").strip() or "15")
        # Asegurar stock mínimo útil para pruebas
        if stock_total < 10:
            stock_total = 12

        stock_reservado = int(r.get("stock_reservado", "0").strip() or "0")
        stock_reservado = min(stock_reservado, stock_total)

        var = db.scalar(select(ProductVariant).where(ProductVariant.sku == sku))
        if not var:
            var = ProductVariant(
                producto_id=db_prod_id,
                sku=sku,
                color=r.get("color", "Único").strip(),
                codigo_color=r.get("codigo_color", "").strip() or None,
                talla=r.get("talla", "U").strip(),
                stock_total=stock_total,
                stock_reservado=stock_reservado,
                codigo_barras=r.get("codigo_barras", "").strip() or None,
                imagen=r.get("imagen", "").strip() or None,
                activo=r.get("activo", "true").lower() in {"true", "1", "t"},
            )
            db.add(var)
        else:
            var.producto_id = db_prod_id
            var.color = r.get("color", "Único").strip()
            var.codigo_color = r.get("codigo_color", "").strip() or None
            var.talla = r.get("talla", "U").strip()
            var.stock_total = max(var.stock_total, stock_total)
            var.codigo_barras = r.get("codigo_barras", "").strip() or None
            var.imagen = r.get("imagen", "").strip() or None
            var.activo = True

        inserted += 1
        if idx % 500 == 0 or idx == len(rows):
            db.flush()
            log_fn(f"    - Procesadas {idx}/{len(rows)} variantes...")

    db.flush()
    log_fn(f"  ✓ {inserted} variantes de catálogo sincronizadas.")
    return inserted


def seed_branch_stock(db, central: Branch, north: Branch, log_fn: Callable[[str], None] = print) -> None:
    """Distribuye el inventario de todas las variantes entre Showroom Central (60%) y Showroom Norte (40%)."""
    log_fn("  → Distribuyendo stock por sede en Showroom Central y Showroom Norte...")
    variants = list(db.scalars(select(ProductVariant).order_by(ProductVariant.id)))

    updated_count = 0
    for v in variants:
        total = max(v.stock_total, 10)
        c_row = db.scalar(
            select(BranchStock).where(
                BranchStock.sucursal_id == central.id,
                BranchStock.variante_id == v.id,
            )
        )
        n_row = db.scalar(
            select(BranchStock).where(
                BranchStock.sucursal_id == north.id,
                BranchStock.variante_id == v.id,
            )
        )

        c_reserved = c_row.stock_reservado if c_row else 0
        n_reserved = n_row.stock_reservado if n_row else 0
        total = max(total, c_reserved + n_reserved + 4)

        central_qty = max(c_reserved, (total * 6) // 10)
        north_qty = max(n_reserved, total - central_qty)

        if not c_row:
            c_row = BranchStock(
                sucursal_id=central.id,
                variante_id=v.id,
                stock_reservado=0,
                stock_minimo=2,
                activo=True,
            )
            db.add(c_row)

        if not n_row:
            n_row = BranchStock(
                sucursal_id=north.id,
                variante_id=v.id,
                stock_reservado=0,
                stock_minimo=2,
                activo=True,
            )
            db.add(n_row)

        c_row.stock_total = central_qty
        n_row.stock_total = north_qty
        v.stock_total = central_qty + north_qty
        v.stock_reservado = c_row.stock_reservado + n_row.stock_reservado
        updated_count += 1

        if updated_count % 1000 == 0:
            db.flush()

    db.flush()
    log_fn(f"  ✓ Stock distribuido en sedes para {updated_count} variantes de producto.")


def seed_test_orders_and_reservations(db, users: dict[str, User], central: Branch, north: Branch, log_fn: Callable[[str], None] = print) -> None:
    """Crea pedidos completados para comprobantes y reservas listas con QR para pruebas en tienda."""
    log_fn("  → Creando cositas de prueba operativas (reservas con QR, ventas emitidas)...")
    cliente = users.get("cliente@drapemind.com")
    vendedor = users.get("vendedor@drapemind.com")
    if not cliente or not vendedor:
        return

    # Buscar dos variantes con stock
    variants = list(db.scalars(select(ProductVariant).where(ProductVariant.stock_total > 5).limit(4)))
    if len(variants) < 2:
        return

    v1, v2 = variants[0], variants[1]
    p1 = db.get(Product, v1.producto_id)
    p2 = db.get(Product, v2.producto_id)

    # 1. Reserva lista para probar escaneo QR y conversión a venta en caja (CU-14, CU-15, CU-16)
    existing_res = db.scalar(
        select(Reservation).where(
            Reservation.usuario_id == cliente.id,
            Reservation.estado == "LISTA",
        )
    )
    if not existing_res:
        test_qr_token = uuid.uuid4()
        reserva = Reservation(
            usuario_id=cliente.id,
            sucursal_id=central.id,
            estado="LISTA",
            codigo_publico=uuid.uuid4(),
            qr_token=test_qr_token,
            vence_at=datetime.now(timezone.utc) + timedelta(days=2),
            observacion="Reserva de prueba lista en Showroom Central para prueba de escaneo QR y POS.",
        )
        db.add(reserva)
        db.flush()

        item_res = ReservationItem(
            reserva_id=reserva.id,
            variante_id=v1.id,
            cantidad=1,
            precio_referencia=p1.precio if p1 else Decimal("149.00"),
        )
        db.add(item_res)
        db.flush()
        log_fn(f"  + Reserva de prueba LISTA creada [ID #{reserva.id}] con QR token {test_qr_token}")

    # 2. Pedido completado ENTREGADO para probar de inmediato la descarga de comprobantes en PDF e imagen (CU-12, CU-37)
    existing_order = db.scalar(
        select(Order).where(
            Order.usuario_id == cliente.id,
            Order.estado == "ENTREGADO",
        )
    )
    if not existing_order:
        subtotal = (p1.precio if p1 else Decimal("149.00")) + (p2.precio if p2 else Decimal("199.00"))
        order = Order(
            usuario_id=cliente.id,
            sucursal_id=central.id,
            estado="ENTREGADO",
            canal="TIENDA",
            tipo_entrega="TIENDA",
            subtotal=subtotal,
            descuento=Decimal("0.00"),
            costo_envio=Decimal("0.00"),
            total=subtotal,
            observacion="Venta presencial de prueba en caja con emisión de comprobante de compra.",
            paid_at=datetime.now(timezone.utc) - timedelta(hours=2),
            completed_at=datetime.now(timezone.utc) - timedelta(hours=2),
        )
        db.add(order)
        db.flush()

        # Items del pedido
        item1 = OrderItem(
            pedido_id=order.id,
            producto_id=p1.id if p1 else None,
            variante_id=v1.id,
            nombre_snapshot=p1.nombre if p1 else "Prenda Exclusiva",
            sku_snapshot=v1.sku,
            color_snapshot=v1.color or "Único",
            talla_snapshot=v1.talla or "M",
            cantidad=1,
            precio_unitario=p1.precio if p1 else Decimal("149.00"),
            descuento=Decimal("0.00"),
            subtotal=p1.precio if p1 else Decimal("149.00"),
        )
        item2 = OrderItem(
            pedido_id=order.id,
            producto_id=p2.id if p2 else None,
            variante_id=v2.id,
            nombre_snapshot=p2.nombre if p2 else "Prenda Atelier",
            sku_snapshot=v2.sku,
            color_snapshot=v2.color or "Único",
            talla_snapshot=v2.talla or "L",
            cantidad=1,
            precio_unitario=p2.precio if p2 else Decimal("199.00"),
            descuento=Decimal("0.00"),
            subtotal=p2.precio if p2 else Decimal("199.00"),
        )
        db.add(item1)
        db.add(item2)

        # Pago asociado
        payment = Payment(
            pedido_id=order.id,
            metodo="EFECTIVO",
            proveedor="CAJA_CENTRAL",
            monto=subtotal,
            moneda="BOB",
            estado="APROBADO",
            referencia_externa=f"REC-POS-{order.id}-TEST",
        )
        db.add(payment)
        db.flush()
        log_fn(f"  + Pedido ENTREGADO de prueba creado [ID #{order.id}] con comprobante listo para descarga PDF/PNG.")

    # 3. Pedido pagado PAGADO para probar avance de estados (CU-39)
    existing_paid = db.scalar(
        select(Order).where(
            Order.usuario_id == cliente.id,
            Order.estado == "PAGADO",
        )
    )
    if not existing_paid:
        p_subtotal = p1.precio if p1 else Decimal("149.00")
        paid_order = Order(
            usuario_id=cliente.id,
            sucursal_id=north.id,
            estado="PAGADO",
            canal="WEB",
            tipo_entrega="DELIVERY",
            subtotal=p_subtotal,
            descuento=Decimal("0.00"),
            costo_envio=Decimal("20.00"),
            total=p_subtotal + Decimal("20.00"),
            observacion="Pedido online pagado listo para empaque y despacho.",
            paid_at=datetime.now(timezone.utc) - timedelta(minutes=30),
        )
        db.add(paid_order)
        db.flush()

        p_item = OrderItem(
            pedido_id=paid_order.id,
            producto_id=p1.id if p1 else None,
            variante_id=v1.id,
            nombre_snapshot=p1.nombre if p1 else "Prenda Exclusiva",
            sku_snapshot=v1.sku,
            color_snapshot=v1.color or "Único",
            talla_snapshot=v1.talla or "M",
            cantidad=1,
            precio_unitario=p_subtotal,
            descuento=Decimal("0.00"),
            subtotal=p_subtotal,
        )
        db.add(p_item)
        db.flush()
        log_fn(f"  + Pedido PAGADO creado [ID #{paid_order.id}] para pruebas de despacho (CU-39).")


def reset_sequences(db, log_fn: Callable[[str], None] = print) -> None:
    """Sincroniza las secuencias de PostgreSQL para evitar colisiones de IDs autoincrementables."""
    tables = [
        "categorias",
        "productos",
        "variantes_producto",
        "usuarios",
        "pedidos",
        "reservas",
        "items_pedido",
        "items_reserva",
        "pagos",
        "sucursales",
        "ciudades",
    ]
    log_fn("  → Reseteando secuencias de PostgreSQL...")
    for tbl in tables:
        try:
            seq_sql = f"SELECT pg_get_serial_sequence('{tbl}', 'id')"
            seq_name = db.execute(text(seq_sql)).scalar()
            if seq_name:
                fix_sql = f"SELECT setval('{seq_name}', COALESCE((SELECT MAX(id) FROM {tbl}), 1))"
                db.execute(text(fix_sql))
        except Exception:
            pass
    db.commit()
    log_fn("  ✓ Secuencias de PostgreSQL sincronizadas al valor máximo actual.")


def run_full_seed(log_fn: Callable[[str], None] = print) -> None:
    """Ejecuta el sembrado completo, modular e idempotente de DrapeMind."""
    log_fn("🌱 ====================================================================")
    log_fn("   DRAPEMIND - SEEDER DE BASE DE DATOS Y CATÁLOGO POBLACIÓN")
    log_fn("====================================================================")

    with SessionLocal() as db:
        log_fn("\n🏬 1. Ciudades y Sucursales (Showrooms)...")
        central, north = seed_cities_and_branches(db, log_fn)
        db.commit()

        log_fn("\n👥 2. Usuarios por Rol, Sucursales y Perfiles...")
        users = seed_users(db, central, north, log_fn)
        db.commit()

        log_fn("\n📁 3. Categorías desde data/categorias.csv...")
        category_map = seed_categories_from_csv(db, log_fn)
        db.commit()

        log_fn("\n👔 4. Productos desde data/productos.csv...")
        product_map = seed_products_from_csv(db, category_map, log_fn)
        db.commit()

        log_fn("\n🎨 5. Variantes desde data/variantes_producto.csv...")
        seed_variants_from_csv(db, product_map, log_fn)
        db.commit()

        log_fn("\n📦 6. Inventario por Sede (BranchStock)...")
        seed_branch_stock(db, central, north, log_fn)
        db.commit()

        log_fn("\n🧾 7. Cositas de Prueba (Reservas QR y Ventas con Comprobante)...")
        seed_test_orders_and_reservations(db, users, central, north, log_fn)
        db.commit()

        log_fn("\n⚡ 8. Reseteo de Secuencias PostgreSQL...")
        reset_sequences(db, log_fn)

    log_fn("\n🎉 ====================================================================")
    log_fn("   ¡SEEDING DE DRAPEMIND COMPLETADO CON ÉXITO!")
    log_fn("   Catálogo con 887 productos, 4296 variantes, usuarios y sedes listos.")
    log_fn("====================================================================\n")


if __name__ == "__main__":
    run_full_seed()
