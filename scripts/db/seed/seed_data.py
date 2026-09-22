"""DrapeMind - Modulo de Seeding Integral y Catalogo Poblacion.

Carga:
1. Sedes y Ciudades configurables (Showrooms y Boutiques).
2. Usuarios para todos los roles (Admin, Encargado, Vendedor, Cajero, Cliente),
   asignacion a sucursales (BranchStaff), direcciones y perfil de estilo IA.
3. Catalogo desde CSVs con limite configurable de prendas (desde 40 hasta 887),
   evitando sobrecarga en PostgreSQL y acelerando el rendimiento del login.
4. Distribucion de inventario por sucursal (BranchStock) entre todas las sedes activas.
5. Proveedores e Insumos textiles (CU-32 y CU-33).
6. Promociones y Reglas de Descuento (CU-36).
7. Temporadas y Colecciones de Moda (CU-31).
8. Pedidos de prueba y reservas activas con QR para tienda (CU-14 a CU-16).
9. Sincronizacion de secuencias PostgreSQL (setval).
"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
import os
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
    OrderItem, Payment, Product, ProductVariant, Promotion, Reservation, ReservationItem,
    Role, Season, Supplier, SupplierProduct, User, UserStatus, UserStyleProfile,
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


def seed_cities_and_branches(db, limit_branches: int = 3, log_fn: Callable[[str], None] = print) -> list[Branch]:
    """Crea ciudades principales y sucursales (Showrooms) de DrapeMind segun limite solicitado."""
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

    # 3. Cochabamba
    cbb_city = db.scalar(
        select(City).where(
            City.nombre == "Cochabamba",
            City.departamento == "Cochabamba",
        )
    )
    if not cbb_city:
        cbb_city = City(nombre="Cochabamba", departamento="Cochabamba", activo=True)
        db.add(cbb_city)
        db.flush()

    all_branch_specs = [
        ("SCZ-CENTRAL", "DrapeMind Showroom Central", "Av. San Martín #450, Equipetrol, Santa Cruz", "70011221", scz_city.id),
        ("SCZ-NORTE", "DrapeMind Showroom Norte", "Av. Banzer esq. 4to Anillo, Santa Cruz", "70011222", scz_city.id),
        ("LPZ-SOPOCACHI", "DrapeMind Atelier La Paz", "Av. 20 de Octubre #2100, Sopocachi, La Paz", "70011223", lpz_city.id),
        ("CBB-CALACALA", "DrapeMind Showroom Cochabamba", "Av. América esq. Pando, Cala Cala, Cochabamba", "70011224", cbb_city.id),
        ("SCZ-SUR", "DrapeMind Boutique Sur", "Av. Santos Dumont #320, Santa Cruz", "70011225", scz_city.id),
    ]

    selected_specs = all_branch_specs[:max(1, min(len(all_branch_specs), limit_branches))]
    branches: list[Branch] = []

    for code, name, address, phone, city_id in selected_specs:
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

    return branches


def seed_users(db, branches: list[Branch], log_fn: Callable[[str], None] = print) -> dict[str, User]:
    """Crea cuentas completas para todos los roles con credenciales y direcciones."""
    b_central = branches[0] if len(branches) > 0 else None
    b_second = branches[1] if len(branches) > 1 else b_central

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
        # Encargados de Tienda
        {
            "nombre": "Elena Encargada Central",
            "email": "encargado@drapemind.com",
            "password": "Encargado12345!",
            "rol": Role.ENCARGADO,
            "telefono": "73344556",
            "direccion": "Av. San Martín #450, Equipetrol, Santa Cruz",
            "branch": b_central,
        },
        {
            "nombre": "Marcos Encargado Norte",
            "email": "encargado.norte@drapemind.com",
            "password": "Encargado12345!",
            "rol": Role.ENCARGADO,
            "telefono": "73344557",
            "direccion": "Av. Banzer esq. 4to Anillo, Santa Cruz",
            "branch": b_second,
        },
        # Vendedores de Piso
        {
            "nombre": "Valeria Vendedora",
            "email": "vendedor@drapemind.com",
            "password": "Vendedor12345!",
            "rol": Role.VENDEDOR,
            "telefono": "74455667",
            "direccion": "Condominio La Riviera #3B, Santa Cruz",
            "branch": b_central,
        },
        # Cajeros
        {
            "nombre": "Carlos Cajero",
            "email": "cajero@drapemind.com",
            "password": "Cajero12345!",
            "rol": Role.CAJERO,
            "telefono": "75566778",
            "direccion": "Barrio Sirari, Calle 5 #45, Santa Cruz",
            "branch": b_central,
        },
        # Clientes
        {
            "nombre": "German Rojas (Cliente VIP)",
            "email": "cliente.german@drapemind.com",
            "password": "Cliente12345!",
            "rol": Role.CLIENTE,
            "telefono": "63014529",
            "direccion": "Av. Las Américas #780, Equipetrol, Santa Cruz",
            "branch": None,
        },
        {
            "nombre": "Camila Cliente",
            "email": "cliente@drapemind.com",
            "password": "Cliente12345!",
            "rol": Role.CLIENTE,
            "telefono": "76677889",
            "direccion": "Av. Monseñor Rivero #220, Santa Cruz",
            "branch": None,
        },
    ]

    user_map: dict[str, User] = {}
    for u in users_data:
        email = u["email"].lower()
        usr = db.scalar(select(User).where(func.lower(User.email) == email))
        if not usr:
            usr = User(
                nombre=u["nombre"],
                email=email,
                password_hash=hash_password(u["password"]),
                telefono=u["telefono"],
                rol=u["rol"],
                estado=UserStatus.ACTIVO,
            )
            db.add(usr)
            db.flush()
            log_fn(f"  + Usuario creado: {usr.nombre} [{usr.email}] ({usr.rol.value})")

            if u["direccion"]:
                addr = Address(
                    usuario_id=usr.id,
                    alias="Principal",
                    direccion=u["direccion"],
                    ciudad="Santa Cruz de la Sierra" if "Santa Cruz" in u["direccion"] else "La Paz",
                    departamento="Santa Cruz" if "Santa Cruz" in u["direccion"] else "La Paz",
                    es_principal=True,
                )
                db.add(addr)
                db.flush()
        else:
            usr.nombre = u["nombre"]
            usr.rol = u["rol"]
            usr.password_hash = hash_password(u["password"])
            usr.estado = UserStatus.ACTIVO
            db.flush()
            log_fn(f"  = Usuario verificado y credenciales sincronizadas: {usr.nombre} [{usr.email}] ({usr.rol.value})")

        # Asignar personal a la sucursal si corresponde
        if u["branch"]:
            staff = db.scalar(
                select(BranchStaff).where(
                    BranchStaff.usuario_id == usr.id,
                    BranchStaff.sucursal_id == u["branch"].id,
                )
            )
            if not staff:
                staff = BranchStaff(
                    usuario_id=usr.id,
                    sucursal_id=u["branch"].id,
                    activo=True,
                )
                db.add(staff)
                db.flush()

        user_map[email] = usr

    # Crear perfil de estilo inicial para clientes
    vip_client = user_map.get("cliente.german@drapemind.com") or user_map.get("cliente@drapemind.com")
    if vip_client:
        style = db.scalar(select(UserStyleProfile).where(UserStyleProfile.usuario_id == vip_client.id))
        if not style:
            style = UserStyleProfile(
                usuario_id=vip_client.id,
                genero="MASCULINO" if "german" in vip_client.email else "FEMENINO",
                estilos_preferidos=["Sastrería Contemporánea", "Minimalista"],
                colores_favoritos=["Azul Marino", "Gris Marengo", "Blanco", "Negro"],
                ocasiones_frecuentes=["Gala", "Directorio", "Cena de Negocios"],
                talla_superior="L",
                talla_inferior="32",
                talla_calzado="42",
                presupuesto_habitual=Decimal("1200.00"),
                silueta_preferida="Tailored Fit / Estructurada",
                adn_estilo_ia="Preferencia por trajes de corte italiano, lino puro y lanas de alpaca de alta gama.",
                completado=True,
            )
            db.add(style)
            db.flush()

    return user_map


def seed_categories_from_csv(db, log_fn: Callable[[str], None] = print) -> dict[int, int]:
    """Carga categorias desde data/categorias.csv resolviendo la jerarquia padre-hijo."""
    csv_file = DATA_DIR / "categorias.csv"
    if not csv_file.exists():
        log_fn("  ! No se encontro categorias.csv en data/; saltando categorias.")
        return {}

    with csv_file.open("r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))

    log_fn(f"  -> Cargando {len(rows)} categorias desde {csv_file.name}...")

    rows_by_id = {int(r["id"].strip()): r for r in rows if r.get("id")}
    category_id_map: dict[int, int] = {}
    pending = set(rows_by_id.keys())

    while pending:
        progress = False
        for cid in list(pending):
            r = rows_by_id[cid]
            parent_raw = (r.get("parent_id") or "").strip()
            parent_cid = int(parent_raw) if parent_raw and parent_raw.isdigit() else None

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

    log_fn(f"  [OK] {len(category_id_map)} categorias sincronizadas correctamente.")
    return category_id_map


def _classify_product_row(r: dict[str, str]) -> tuple[str, str]:
    """Clasifica una prenda de productos.csv por genero y familia para un sembrado equilibrado."""
    gen = (r.get("genero_objetivo") or "UNISEX").strip().upper()
    if gen not in ("HOMBRE", "MUJER", "UNISEX"):
        gen = "UNISEX"
    name = (r.get("nombre") or "").lower()
    if any(k in name for k in ["dress", "vestido", "skirt", "falda"]):
        fam = "VESTIDOS_FALDAS"
    elif any(k in name for k in ["shirt", "camisa", "blouse", "blusa", "t-shirt", "tshirt", "polera", "polo", "top", "tee"]):
        fam = "TOPS"
    elif any(k in name for k in ["jean", "trouser", "pantalon", "jogger", "short", "legging"]):
        fam = "BOTTOMS"
    elif any(k in name for k in ["jacket", "blazer", "chaqueta", "coat", "sweater", "cardigan", "chamarra", "hoodie", "abrigo"]):
        fam = "OUTERWEAR"
    elif any(k in name for k in ["shoe", "boot", "sneaker", "heel", "flat", "sandal", "zapato", "bota", "calzado", "mocas"]):
        fam = "FOOTWEAR"
    else:
        fam = "ACCESORIOS"
    return gen, fam


def sample_balanced_products(
    all_rows: list[dict[str, str]],
    limit_products: int | None = None,
    women_count: int | None = None,
    men_count: int | None = None,
    unisex_count: int | None = None,
    tops_count: int | None = None,
    bottoms_count: int | None = None,
    shoes_count: int | None = None,
    dresses_count: int | None = None,
    outerwear_count: int | None = None,
) -> list[dict[str, str]]:
    """Distribuye equitativamente las prendas entre generos y familias para un showroom realista."""
    has_custom_counts = (women_count is not None) or (men_count is not None) or (unisex_count is not None)
    has_family_counts = any(c is not None for c in [tops_count, bottoms_count, shoes_count, dresses_count, outerwear_count])
    if not limit_products and not has_custom_counts and not has_family_counts:
        return all_rows

    buckets: dict[str, dict[str, list[dict[str, str]]]] = {
        "MUJER": {"TOPS": [], "VESTIDOS_FALDAS": [], "BOTTOMS": [], "FOOTWEAR": [], "OUTERWEAR": [], "ACCESORIOS": []},
        "HOMBRE": {"TOPS": [], "BOTTOMS": [], "FOOTWEAR": [], "OUTERWEAR": [], "ACCESORIOS": [], "VESTIDOS_FALDAS": []},
        "UNISEX": {"TOPS": [], "FOOTWEAR": [], "ACCESORIOS": [], "BOTTOMS": [], "OUTERWEAR": [], "VESTIDOS_FALDAS": []},
    }

    for r in all_rows:
        gen, fam = _classify_product_row(r)
        buckets[gen][fam].append(r)

    # Si se especificaron metas explicitas por tipo/familia de prenda
    if has_family_counts:
        fam_targets = {
            "TOPS": tops_count or 0,
            "BOTTOMS": bottoms_count or 0,
            "FOOTWEAR": shoes_count or 0,
            "VESTIDOS_FALDAS": dresses_count or 0,
            "OUTERWEAR": outerwear_count or 0,
        }
        selected: list[dict[str, str]] = []
        for fam, target in fam_targets.items():
            if target <= 0:
                continue
            fam_items: list[dict[str, str]] = []
            for gen in ["MUJER", "HOMBRE", "UNISEX"]:
                fam_items.extend(buckets[gen][fam])
            selected.extend(fam_items[:target])

        if limit_products and len(selected) < limit_products:
            needed = limit_products - len(selected)
            remainder = [r for r in all_rows if r not in selected]
            selected.extend(remainder[:needed])
        return selected

    if has_custom_counts:
        w_target = women_count or 0
        m_target = men_count or 0
        u_target = unisex_count or 0
    else:
        tot = limit_products or 60
        w_target = int(tot * 0.45)
        m_target = int(tot * 0.40)
        u_target = max(0, tot - w_target - m_target)

    def extract_from_gender(gen: str, target: int) -> list[dict[str, str]]:
        if target <= 0:
            return []
        fams = [f for f, items in buckets[gen].items() if len(items) > 0]
        if not fams:
            return []
        per_fam = max(1, target // len(fams))
        sampled: list[dict[str, str]] = []
        for f in fams:
            sampled.extend(buckets[gen][f][:per_fam])
        if len(sampled) < target:
            leftover = [r for f in fams for r in buckets[gen][f] if r not in sampled]
            sampled.extend(leftover[: target - len(sampled)])
        elif len(sampled) > target:
            sampled = sampled[:target]
        return sampled

    selected = []
    selected.extend(extract_from_gender("MUJER", w_target))
    selected.extend(extract_from_gender("HOMBRE", m_target))
    selected.extend(extract_from_gender("UNISEX", u_target))
    return selected


def seed_products_from_csv(
    db,
    category_id_map: dict[int, int],
    limit_products: int | None = None,
    women_count: int | None = None,
    men_count: int | None = None,
    unisex_count: int | None = None,
    tops_count: int | None = None,
    bottoms_count: int | None = None,
    shoes_count: int | None = None,
    dresses_count: int | None = None,
    outerwear_count: int | None = None,
    log_fn: Callable[[str], None] = print,
) -> dict[int, int]:
    """Carga productos desde data/productos.csv con muestreo equilibrado por genero y familias."""
    csv_file = DATA_DIR / "productos.csv"
    if not csv_file.exists():
        log_fn("  ! No se encontro productos.csv en data/; saltando productos.")
        return {}

    with csv_file.open("r", encoding="utf-8-sig", newline="") as f:
        all_rows = list(csv.DictReader(f))

    rows = sample_balanced_products(
        all_rows,
        limit_products=limit_products,
        women_count=women_count,
        men_count=men_count,
        unisex_count=unisex_count,
        tops_count=tops_count,
        bottoms_count=bottoms_count,
        shoes_count=shoes_count,
        dresses_count=dresses_count,
        outerwear_count=outerwear_count,
    )
    log_fn(f"  -> Cargando {len(rows)} productos con distribucion balanceada por genero y familias de ropa...")

    product_id_map: dict[int, int] = {}
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

        prod = db.scalar(select(Product).where(Product.tags_ai.contains([marker])))
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
        if idx % 100 == 0 or idx == len(rows):
            log_fn(f"    - Procesados {idx}/{len(rows)} productos...")

    log_fn(f"  [OK] {len(product_id_map)} productos sincronizados con exito.")
    return product_id_map


def seed_variants_from_csv(db, product_id_map: dict[int, int], log_fn: Callable[[str], None] = print) -> int:
    """Carga variantes desde data/variantes_producto.csv unicamente para los productos seleccionados."""
    csv_file = DATA_DIR / "variantes_producto.csv"
    if not csv_file.exists():
        log_fn("  ! No se encontro variantes_producto.csv en data/; saltando variantes.")
        return 0

    with csv_file.open("r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))

    log_fn(f"  -> Filtrando y cargando variantes para los {len(product_id_map)} productos activos...")
    inserted = 0

    for idx, r in enumerate(rows, start=1):
        source_prod_id = int(r["producto_id"].strip())
        db_prod_id = product_id_map.get(source_prod_id)
        if not db_prod_id:
            continue

        sku = r["sku"].strip()
        stock_total = int(r.get("stock_total", "15").strip() or "15")
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
            var.talla = r.get("talla", "U").strip()
            var.stock_total = max(var.stock_total, stock_total)
            var.activo = True

        inserted += 1
        if inserted % 250 == 0:
            db.flush()

    db.flush()
    log_fn(f"  [OK] {inserted} variantes de catalogo vinculadas y sincronizadas.")
    return inserted


def seed_branch_stock(db, branches: list[Branch], log_fn: Callable[[str], None] = print) -> None:
    """Distribuye el inventario proporcionalmente entre todas las sucursales creadas."""
    if not branches:
        return
    log_fn(f"  -> Distribuyendo stock de catalogo entre {len(branches)} sucursales...")
    variants = list(db.scalars(select(ProductVariant).order_by(ProductVariant.id)))
    updated_count = 0

    if len(branches) == 1:
        weights = [1.0]
    elif len(branches) == 2:
        weights = [0.60, 0.40]
    elif len(branches) == 3:
        weights = [0.50, 0.30, 0.20]
    else:
        weights = [1.0 / len(branches)] * len(branches)

    for v in variants:
        total = max(v.stock_total, 12)
        allocated_total = 0

        for b_idx, b in enumerate(branches):
            b_row = db.scalar(
                select(BranchStock).where(
                    BranchStock.sucursal_id == b.id,
                    BranchStock.variante_id == v.id,
                )
            )
            qty = max(2, int(total * weights[b_idx]))
            if not b_row:
                b_row = BranchStock(
                    sucursal_id=b.id,
                    variante_id=v.id,
                    stock_total=qty,
                    stock_reservado=0,
                    stock_minimo=2,
                    activo=True,
                )
                db.add(b_row)
            else:
                b_row.stock_total = qty
                b_row.activo = True

            allocated_total += qty

        v.stock_total = allocated_total
        updated_count += 1
        if updated_count % 500 == 0:
            db.flush()

    db.flush()
    log_fn(f"  [OK] Stock distribuido en {len(branches)} sedes para {updated_count} variantes.")


def seed_suppliers_and_supplies(db, log_fn: Callable[[str], None] = print) -> None:
    """Carga proveedores y catalogo de insumos textiles (CU-32 y CU-33)."""
    log_fn("  -> Sembrando agenda de proveedores e insumos de materia prima...")
    suppliers_data = [
        {
            "nombre_empresa": "Hilandería Andina Textil S.A.",
            "nit": "1029384751",
            "contacto_nombre": "Carlos Mendoza",
            "telefono": "71524367",
            "email": "ventas@andinotextil.com",
            "ciudad": "La Paz",
            "direccion": "Parque Industrial Calle 4 #120, El Alto",
            "categoria_suministro": "Lanas y Tejidos de Alpaca",
            "supplies": [
                ("Lana Baby Alpaca 100%", "SUP-ALP-01", "Fibras Nobles", "Kilos", Decimal("220.00"), 45, 7, "DISPONIBLE"),
                ("Lana Mezcla Merino y Alpaca", "SUP-MER-02", "Hilados", "Kilos", Decimal("160.00"), 60, 5, "DISPONIBLE"),
            ],
        },
        {
            "nombre_empresa": "Sedas & Linos de Santa Cruz Ltda.",
            "nit": "2049182736",
            "contacto_nombre": "Mariana Vaca",
            "telefono": "77891234",
            "email": "contacto@sedaslinos.com.bo",
            "ciudad": "Santa Cruz de la Sierra",
            "direccion": "Av. Doble Vía a La Guardia Km 6, Santa Cruz",
            "categoria_suministro": "Lino Italiano y Sedas",
            "supplies": [
                ("Lino Belga Crudo de Confección", "SUP-LIN-10", "Telas y Confección", "Metros", Decimal("85.00"), 120, 4, "DISPONIBLE"),
                ("Seda Mulberry Natural Satinada", "SUP-SED-04", "Tejidos Finos", "Metros", Decimal("195.00"), 30, 10, "BAJO_PEDIDO"),
            ],
        },
        {
            "nombre_empresa": "Confecciones Altiplano & Botones",
            "nit": "3091827465",
            "contacto_nombre": "Roberto Choque",
            "telefono": "73098124",
            "email": "insumos@confeccionesaltiplano.bo",
            "ciudad": "Cochabamba",
            "direccion": "Zona Recoleta #450, Cochabamba",
            "categoria_suministro": "Avíos, Botones de Cuerno y Forrería",
            "supplies": [
                ("Botones de Cuerno Natural Sastrero", "SUP-BOT-01", "Avíos y Forros", "Gruesas (144u)", Decimal("75.00"), 80, 3, "DISPONIBLE"),
                ("Forrería Bemberg Transpirable", "SUP-BEM-05", "Forros Sastreros", "Metros", Decimal("45.00"), 150, 4, "DISPONIBLE"),
            ],
        },
    ]

    for s_info in suppliers_data:
        supp = db.scalar(select(Supplier).where(Supplier.nombre_empresa == s_info["nombre_empresa"]))
        if not supp:
            supp = Supplier(
                nombre_empresa=s_info["nombre_empresa"],
                nit=s_info["nit"],
                contacto_nombre=s_info["contacto_nombre"],
                telefono=s_info["telefono"],
                email=s_info["email"],
                ciudad=s_info["ciudad"],
                direccion=s_info["direccion"],
                categoria_suministro=s_info["categoria_suministro"],
                activo=True,
            )
            db.add(supp)
            db.flush()

        for nom, sku, cat, um, costo, stock, tiempo, est in s_info["supplies"]:
            sp = db.scalar(select(SupplierProduct).where(SupplierProduct.sku_proveedor == sku))
            if not sp:
                sp = SupplierProduct(
                    proveedor_id=supp.id,
                    nombre_suministro=nom,
                    sku_proveedor=sku,
                    categoria=cat,
                    unidad_medida=um,
                    costo_unitario=costo,
                    cantidad_disponible=stock,
                    tiempo_entrega_dias=tiempo,
                    estado=est,
                    activo=True,
                )
                db.add(sp)

    db.flush()
    log_fn("  [OK] Proveedores e insumos textiles registrados con éxito.")


def seed_promotions(db, log_fn: Callable[[str], None] = print) -> None:
    """Carga promociones sastreras vigentes (CU-36)."""
    log_fn("  -> Sembrando reglas de descuento y promociones activas...")
    now = datetime.now(timezone.utc)
    promos = [
        {
            "codigo": "BIENVENIDA15",
            "descripcion": "15% de descuento en primera compra sastrera en boutique o web",
            "tipo_descuento": "PORCENTAJE",
            "valor_descuento": Decimal("15.00"),
            "monto_minimo_compra": Decimal("100.00"),
            "fecha_inicio": now - timedelta(days=10),
            "fecha_fin": now + timedelta(days=90),
            "limite_usos": 200,
            "usos_actuales": 12,
        },
        {
            "codigo": "VIP-ATELIER",
            "descripcion": "25% de descuento exclusivo para clientes VIP con reserva de alta costura",
            "tipo_descuento": "PORCENTAJE",
            "valor_descuento": Decimal("25.00"),
            "monto_minimo_compra": Decimal("600.00"),
            "fecha_inicio": now - timedelta(days=5),
            "fecha_fin": now + timedelta(days=120),
            "limite_usos": 50,
            "usos_actuales": 4,
        },
        {
            "codigo": "OUTFIT-ALTAIR",
            "descripcion": "Bono de Bs 80 por outfits combinados de 3 o más prendas recomendadas por IA",
            "tipo_descuento": "MONTO_FIJO",
            "valor_descuento": Decimal("80.00"),
            "monto_minimo_compra": Decimal("450.00"),
            "fecha_inicio": now - timedelta(days=3),
            "fecha_fin": now + timedelta(days=60),
            "limite_usos": 100,
            "usos_actuales": 8,
        },
    ]

    for p in promos:
        existing = db.scalar(select(Promotion).where(Promotion.codigo == p["codigo"]))
        if not existing:
            promo = Promotion(
                codigo=p["codigo"],
                descripcion=p["descripcion"],
                tipo_descuento=p["tipo_descuento"],
                valor_descuento=p["valor_descuento"],
                monto_minimo_compra=p["monto_minimo_compra"],
                fecha_inicio=p["fecha_inicio"],
                fecha_fin=p["fecha_fin"],
                limite_usos=p["limite_usos"],
                usos_actuales=p["usos_actuales"],
                activo=True,
            )
            db.add(promo)

    db.flush()
    log_fn("  [OK] Promociones y cupones comerciales sincronizados.")


def seed_seasons(db, log_fn: Callable[[str], None] = print) -> None:
    """Carga temporadas y colecciones de moda (CU-31)."""
    log_fn("  -> Sembrando temporadas y colecciones sastreras...")
    now = datetime.now(timezone.utc)
    seasons = [
        {
            "nombre": "Otoño-Invierno 2026",
            "codigo": "OI-2026",
            "descripcion": "Colección de alta costura con abrigos de alpaca, trajes cruzados y lanas finas.",
            "fecha_inicio": now - timedelta(days=60),
            "fecha_fin": now + timedelta(days=90),
        },
        {
            "nombre": "Primavera Sastrera 2026",
            "codigo": "PS-2026",
            "descripcion": "Cortes ligeros de lino puro y mezclas de seda para temporadas templadas y cálidas.",
            "fecha_inicio": now + timedelta(days=30),
            "fecha_fin": now + timedelta(days=180),
        },
        {
            "nombre": "Cápsula Altair Lujo",
            "codigo": "CAP-ALTAIR",
            "descripcion": "Edición limitada diseñada en colaboración con los estilistas del motor Altair.",
            "fecha_inicio": now - timedelta(days=15),
            "fecha_fin": now + timedelta(days=240),
        },
    ]

    for s in seasons:
        existing = db.scalar(select(Season).where(Season.codigo == s["codigo"]))
        if not existing:
            season = Season(
                nombre=s["nombre"],
                codigo=s["codigo"],
                descripcion=s["descripcion"],
                fecha_inicio=s["fecha_inicio"],
                fecha_fin=s["fecha_fin"],
                activo=True,
            )
            db.add(season)

    db.flush()
    log_fn("  [OK] Temporadas y colecciones sastreras registradas.")


def seed_test_orders_and_reservations(db, users: dict[str, User], branches: list[Branch], log_fn: Callable[[str], None] = print) -> None:
    """Crea pedidos completados para comprobantes y reservas listas con QR para pruebas en tienda."""
    log_fn("  -> Creando datos de prueba operativos (reservas con QR, ventas emitidas)...")
    cliente_vip = users.get("cliente.german@drapemind.com") or users.get("cliente@drapemind.com")
    cliente_reg = users.get("cliente@drapemind.com") or cliente_vip
    vendedor = users.get("vendedor@drapemind.com")
    c_branch = branches[0] if branches else None

    if not cliente_vip or not c_branch:
        return

    variants = list(db.scalars(select(ProductVariant).where(ProductVariant.stock_total > 5).limit(4)))
    if len(variants) < 2:
        return

    v1, v2 = variants[0], variants[1]
    p1 = db.get(Product, v1.producto_id)
    p2 = db.get(Product, v2.producto_id)

    # 1. Reserva lista para probar escaneo QR y POS
    existing_res = db.scalar(select(Reservation).where(Reservation.usuario_id == cliente_vip.id, Reservation.estado == "LISTA"))
    if not existing_res:
        test_qr_token = uuid.uuid4()
        reserva = Reservation(
            usuario_id=cliente_vip.id,
            sucursal_id=c_branch.id,
            estado="LISTA",
            codigo_publico=uuid.uuid4(),
            qr_token=test_qr_token,
            vence_at=datetime.now(timezone.utc) + timedelta(days=2),
            observacion="Reserva sastrera lista en Showroom Central para prueba de escaneo QR y POS.",
        )
        db.add(reserva)
        db.flush()

        item_res = ReservationItem(
            reserva_id=reserva.id,
            variante_id=v1.id,
            cantidad=1,
            precio_referencia=p1.precio if p1 else Decimal("199.00"),
        )
        db.add(item_res)
        db.flush()
        log_fn(f"  + Reserva LISTA con QR creada [ID #{reserva.id}] para cliente {cliente_vip.nombre}.")

    # 2. Pedido completado para comprobante y top cliente (German Rojas)
    existing_order = db.scalar(select(Order).where(Order.usuario_id == cliente_vip.id, Order.estado == "ENTREGADO"))
    if not existing_order:
        subtotal = (p1.precio if p1 else Decimal("199.00")) + (p2.precio if p2 else Decimal("199.00"))
        order = Order(
            usuario_id=cliente_vip.id,
            sucursal_id=c_branch.id,
            estado="ENTREGADO",
            canal="TIENDA",
            tipo_entrega="TIENDA",
            subtotal=subtotal,
            descuento=Decimal("0.00"),
            costo_envio=Decimal("0.00"),
            total=subtotal,
            observacion="Compra sastrera formal completada en Showroom Central.",
            paid_at=datetime.now(timezone.utc) - timedelta(days=2),
            completed_at=datetime.now(timezone.utc) - timedelta(days=2),
        )
        db.add(order)
        db.flush()

        item1 = OrderItem(
            pedido_id=order.id,
            producto_id=p1.id if p1 else None,
            variante_id=v1.id,
            nombre_snapshot=p1.nombre if p1 else "Prenda Atelier",
            sku_snapshot=v1.sku,
            color_snapshot=v1.color or "Único",
            talla_snapshot=v1.talla or "M",
            cantidad=1,
            precio_unitario=p1.precio if p1 else Decimal("199.00"),
            descuento=Decimal("0.00"),
            subtotal=p1.precio if p1 else Decimal("199.00"),
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
        log_fn(f"  + Pedido ENTREGADO creado [ID #{order.id}] con comprobante listo para auditoría.")


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
        "items_carrito",
        "carritos",
        "movimientos_inventario",
        "pagos",
        "sucursales",
        "ciudades",
        "proveedores",
        "proveedor_suministros",
        "promociones",
        "temporadas_colecciones",
    ]
    log_fn("  -> Reseteando secuencias de PostgreSQL...")
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
    log_fn("  [OK] Secuencias de PostgreSQL sincronizadas al valor maximo actual.")


def run_full_seed(
    products_limit: int | None = None,
    branches_limit: int | None = None,
    women_count: int | None = None,
    men_count: int | None = None,
    unisex_count: int | None = None,
    tops_count: int | None = None,
    bottoms_count: int | None = None,
    shoes_count: int | None = None,
    dresses_count: int | None = None,
    outerwear_count: int | None = None,
    force: bool = False,
    reset: bool = False,
    log_fn: Callable[[str], None] = print,
) -> None:
    """Ejecuta el sembrado completo, modular y configurable de DrapeMind."""
    parser = argparse.ArgumentParser(description="DrapeMind Database Seeder")
    parser.add_argument("--products", "-p", "--limit-products", type=int, default=None, help="Limite maximo de productos a cargar (ej. 50, 100, 200)")
    parser.add_argument("--women-count", "--women", type=int, default=None, help="Cantidad especifica de prendas de mujer a sembrar")
    parser.add_argument("--men-count", "--men", type=int, default=None, help="Cantidad especifica de prendas de hombre a sembrar")
    parser.add_argument("--unisex-count", "--unisex", type=int, default=None, help="Cantidad especifica de prendas unisex a sembrar")
    parser.add_argument("--tops", "--tops-count", type=int, default=None, help="Cantidad especifica de poleras/camisas/blusas a sembrar")
    parser.add_argument("--bottoms", "--bottoms-count", type=int, default=None, help="Cantidad especifica de pantalones/shorts a sembrar")
    parser.add_argument("--shoes", "--footwear", "--shoes-count", type=int, default=None, help="Cantidad especifica de zapatos/calzado a sembrar")
    parser.add_argument("--dresses", "--dresses-count", type=int, default=None, help="Cantidad especifica de vestidos/faldas a sembrar")
    parser.add_argument("--outerwear", "--outerwear-count", type=int, default=None, help="Cantidad especifica de abrigos/chaquetas a sembrar")
    parser.add_argument("--branches", "-b", type=int, default=None, help="Cantidad de sucursales a crear (1 a 5)")
    parser.add_argument("--reset", action="store_true", help="Limpia las tablas antes de sembrar")
    parser.add_argument("--force", action="store_true", help="Fuerza el sembrado aunque existan productos")
    parser.add_argument("--quick", action="store_true", help="Modo ultra-rapido (40 productos, 2 sucursales)")
    parser.add_argument("--standard", action="store_true", help="Modo estandar (120 productos, 3 sucursales)")
    parser.add_argument("--full", action="store_true", help="Modo catalogo completo (todos los 887 productos)")

    # Parsear solo si ejecutado directamente o pasar argumentos de sys.argv
    cli_args, _ = parser.parse_known_args()

    # Combinar parametros explicitos de funcion con CLI o Variables de Entorno
    is_reset = reset or cli_args.reset or ("--reset" in sys.argv) or (os.environ.get("SEED_RESET", "").lower() in {"1", "true", "yes"})
    is_force = force or cli_args.force or ("--force" in sys.argv) or (os.environ.get("SEED_FORCE", "").lower() in {"1", "true", "yes"})

    final_products = products_limit or cli_args.products
    final_branches = branches_limit or cli_args.branches
    final_women = women_count or cli_args.women_count
    final_men = men_count or cli_args.men_count
    final_unisex = unisex_count or cli_args.unisex_count
    final_tops = tops_count or cli_args.tops
    final_bottoms = bottoms_count or cli_args.bottoms
    final_shoes = shoes_count or cli_args.shoes
    final_dresses = dresses_count or cli_args.dresses
    final_outerwear = outerwear_count or cli_args.outerwear

    if cli_args.quick:
        final_products = 40
        final_branches = 2
    elif cli_args.standard:
        final_products = 120
        final_branches = 3
    elif cli_args.full:
        final_products = None  # Carga completa
        final_branches = 5

    # Si no se definieron por CLI ni parametros, revisar variables de entorno
    if final_products is None and os.environ.get("SEED_MAX_PRODUCTS"):
        try:
            final_products = int(os.environ["SEED_MAX_PRODUCTS"])
        except ValueError:
            pass

    if final_branches is None and os.environ.get("SEED_MAX_BRANCHES"):
        try:
            final_branches = int(os.environ["SEED_MAX_BRANCHES"])
        except ValueError:
            pass

    # Si se ejecuta en terminal interactivo (TTY) y no se indico nada, solicitar al usuario
    if final_products is None and sys.stdin.isatty() and not is_force and not cli_args.quick and not cli_args.standard and not cli_args.full:
        print("\n" + "=" * 70)
        print("  DRAPEMIND - CONFIGURACION DE POBLACION DE BASE DE DATOS")
        print("=" * 70)
        print("  Selecciona el tamano del catalogo para optimizar memoria y login:")
        print("  [1] Modo Ligero (40 prendas, 2 sucursales) - Ideal para servidores ligeros y login instantaneo")
        print("  [2] Modo Estandar (120 prendas, 3 sucursales) - Recomendado para demos completas")
        print("  [3] Modo Catalogo Completo (887 prendas, 4,296 variantes) - Carga masiva completa")
        print("  [4] Personalizado Rapido (Ingresar cantidad total de prendas y sucursales)")
        print("  [5] Personalizado Detallado (Elegir por genero y categorias: poleras, pantalones, calzado...)")
        print("=" * 70)
        try:
            choice = input("  Ingresa tu opcion [1-5, por defecto 1]: ").strip()
            if choice == "2":
                final_products = 120
                final_branches = 3
            elif choice == "3":
                final_products = None
                final_branches = 5
            elif choice == "4":
                p_in = input("  ¿Cuantas prendas deseas cargar? (ej. 60): ").strip()
                b_in = input("  ¿Cuantas sucursales deseas crear? (1 a 5, ej. 2): ").strip()
                final_products = int(p_in) if p_in.isdigit() else 60
                final_branches = int(b_in) if b_in.isdigit() else 2
                r_in = input("  ¿Deseas limpiar tablas antes de sembrar? (s/n, defecto s): ").strip().lower()
                if r_in in {"", "s", "si", "y", "yes"}:
                    is_reset = True
            elif choice == "5":
                print("\n  --- Configuracion Detallada por Categoria y Genero ---")
                w_in = input("  Prendas de Mujer (Enter para omitir o ej. 25): ").strip()
                m_in = input("  Prendas de Hombre (Enter para omitir o ej. 20): ").strip()
                u_in = input("  Prendas Unisex (Enter para omitir o ej. 15): ").strip()
                t_in = input("  Poleras / Camisas / Blusas (Tops)? (Enter para omitir o ej. 15): ").strip()
                bt_in = input("  Pantalones / Shorts (Bottoms)? (Enter para omitir o ej. 15): ").strip()
                sh_in = input("  Calzado / Zapatos (Footwear)? (Enter para omitir o ej. 10): ").strip()
                dr_in = input("  Vestidos / Faldas (Dresses)? (Enter para omitir o ej. 10): ").strip()
                ow_in = input("  Abrigos / Chaquetas (Outerwear)? (Enter para omitir o ej. 10): ").strip()
                br_in = input("  ¿Cuantas sucursales deseas crear? (1 a 5, defecto 2): ").strip()
                r_in = input("  ¿Deseas limpiar tablas antes de sembrar? (s/n, defecto s): ").strip().lower()

                final_women = int(w_in) if w_in.isdigit() else None
                final_men = int(m_in) if m_in.isdigit() else None
                final_unisex = int(u_in) if u_in.isdigit() else None
                final_tops = int(t_in) if t_in.isdigit() else None
                final_bottoms = int(bt_in) if bt_in.isdigit() else None
                final_shoes = int(sh_in) if sh_in.isdigit() else None
                final_dresses = int(dr_in) if dr_in.isdigit() else None
                final_outerwear = int(ow_in) if ow_in.isdigit() else None
                final_branches = int(br_in) if br_in.isdigit() else 2

                if r_in in {"", "s", "si", "y", "yes"}:
                    is_reset = True

                cat_sum = sum(filter(None, [final_tops, final_bottoms, final_shoes, final_dresses, final_outerwear]))
                gen_sum = sum(filter(None, [final_women, final_men, final_unisex]))
                final_products = cat_sum or gen_sum or 60
            else:
                final_products = 40
                final_branches = 2
        except (KeyboardInterrupt, EOFError):
            final_products = 40
            final_branches = 2

    # Por defecto, si no se definio nada en ejecucion automatica, 60 prendas es ideal
    if final_products is None and not cli_args.full:
        final_products = 60
    if final_branches is None:
        final_branches = 3

    log_fn("====================================================================")
    log_fn("   DRAPEMIND - SEEDER DE BASE DE DATOS Y CATALOGO PERSONALIZADO")
    log_fn(f"   Configuracion: {final_products or 'Todas (887)'} prendas | {final_branches} sucursales")
    log_fn("====================================================================")

    with SessionLocal() as db:
        prod_count = db.scalar(select(func.count(Product.id))) or 0

        if prod_count > 0 and not is_force and not is_reset:
            log_fn(f"\n[AVISO] La base de datos ya contiene {prod_count} productos.")
            log_fn("  El sembrado ha sido omitido para preservar tus datos y evitar duplicados.")
            log_fn("  (Para reiniciar y sembrar limpio: python -m scripts.db.seed_data --reset --products 60)")
            log_fn("  (Para forzar sembrado adicional: python -m scripts.db.seed_data --force)\n")
            return

        if is_reset:
            log_fn("\n[MODO RESET] Limpiando tablas de catalogo, stock, pedidos, carritos y proveedores...")
            try:
                db.execute(
                    text(
                        "TRUNCATE TABLE items_pedido, items_reserva, pagos, pedidos, reservas, "
                        "movimientos_inventario, items_carrito, carritos, stock_sucursal, "
                        "variantes_producto, productos, proveedor_suministros, proveedores, "
                        "promociones, temporadas_colecciones CASCADE;"
                    )
                )
                db.commit()
                log_fn("  [OK] Tablas operativas reseteadas a cero.")
            except Exception as exc:
                db.rollback()
                log_fn(f"  ! Aviso al resetear tablas: {exc}")

        log_fn("\n1. Ciudades y Sucursales (Showrooms)...")
        branches = seed_cities_and_branches(db, limit_branches=final_branches, log_fn=log_fn)
        db.commit()

        log_fn("\n2. Usuarios por Rol, Sucursales y Perfiles...")
        users = seed_users(db, branches, log_fn)
        db.commit()

        log_fn("\n3. Categorias de Moda...")
        category_map = seed_categories_from_csv(db, log_fn)
        db.commit()

        log_fn(f"\n4. Productos ({final_products or 'Todos'} prendas)...")
        product_map = seed_products_from_csv(
            db,
            category_map,
            limit_products=final_products,
            women_count=final_women,
            men_count=final_men,
            unisex_count=final_unisex,
            tops_count=final_tops,
            bottoms_count=final_bottoms,
            shoes_count=final_shoes,
            dresses_count=final_dresses,
            outerwear_count=final_outerwear,
            log_fn=log_fn,
        )
        db.commit()

        log_fn("\n5. Variantes de Color y Talla...")
        seed_variants_from_csv(db, product_map, log_fn)
        db.commit()

        log_fn("\n6. Distribucion de Stock por Sucursales...")
        seed_branch_stock(db, branches, log_fn)
        db.commit()

        log_fn("\n7. Proveedores e Insumos Textiles (CU-32 y CU-33)...")
        seed_suppliers_and_supplies(db, log_fn)
        db.commit()

        log_fn("\n8. Promociones y Reglas de Descuento (CU-36)...")
        seed_promotions(db, log_fn)
        db.commit()

        log_fn("\n9. Temporadas y Colecciones (CU-31)...")
        seed_seasons(db, log_fn)
        db.commit()

        log_fn("\n10. Datos de Prueba Operativos (Reservas con QR y Comprobantes)...")
        seed_test_orders_and_reservations(db, users, branches, log_fn)
        db.commit()

        log_fn("\n11. Reseteo y Sincronizacion de Secuencias PostgreSQL...")
        reset_sequences(db, log_fn)

    log_fn("\n====================================================================")
    log_fn("   SEEDING DE DRAPEMIND COMPLETADO CON EXITO")
    log_fn(f"   Base de datos ligera, optimizada y lista ({final_products or '887'} prendas, {final_branches} sedes).")
    log_fn("====================================================================\n")


# Alias de compatibilidad para db_manager_gui y scripts legacy
seed_categories = seed_categories_from_csv
seed_products = seed_products_from_csv


if __name__ == "__main__":
    run_full_seed()

