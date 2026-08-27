"""
DrapeMind - Módulo de Seeding de Datos Iniciales Extendido
Inserta categorías de moda, catálogo amplio de productos (30+) con variantes de color/talla/stock,
usuarios base (ADMIN, VENDEDOR, CLIENTE), direcciones y datos de prueba.
"""

import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from decimal import Decimal
from pathlib import Path
from typing import Callable

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy import delete, func, select
from app.core.security import hash_password
from app.db.session import SessionLocal
from app.models.entities import (
    Address, Category, Gender, Product, ProductVariant, Role, User, UserStatus,
)


def seed_categories(db, log_fn: Callable[[str], None] = print) -> dict[str, Category]:
    """Crea las categorías principales de moda."""
    categories_data = [
        {"nombre": "Poleras & Camisetas", "slug": "poleras-camisetas", "desc": "Poleras básicas, gráficas, oversize y camisetas de algodón suave."},
        {"nombre": "Camisas & Blusas", "slug": "camisas-blusas", "desc": "Camisas casuales, formales, de lino y blusas elegantes."},
        {"nombre": "Pantalones & Jeans", "slug": "pantalones-jeans", "desc": "Jeans, pantalones chinos, de vestir, joggers y bermudas."},
        {"nombre": "Vestidos & Faldas", "slug": "vestidos-faldas", "desc": "Vestidos de fiesta, cóctel, midi, casuales y faldas modernas."},
        {"nombre": "Chaquetas & Abrigos", "slug": "chaquetas-abrigos", "desc": "Blazers, parkas térmicas, chamarras de cuero y gabardinas."},
        {"nombre": "Calzado & Zapatos", "slug": "calzado-zapatos", "desc": "Zapatos formales, zapatillas urbanas, botas chelsea y mocasines."},
        {"nombre": "Accesorios & Bolsos", "slug": "accesorios-bolsos", "desc": "Cinturones de cuero, bufandas, bolsos, relojes y gafas de sol."},
        {"nombre": "Deportes & Athleisure", "slug": "deportes-athleisure", "desc": "Prendas deportivas cómodas, licras, hoodies y conjuntos aerodinámicos."},
    ]

    cat_map = {}
    for cdata in categories_data:
        existing = db.scalar(select(Category).where(Category.slug == cdata["slug"]))
        if not existing:
            cat = Category(
                nombre=cdata["nombre"],
                slug=cdata["slug"],
                descripcion=cdata["desc"],
                activo=True,
            )
            db.add(cat)
            db.flush()
            cat_map[cdata["slug"]] = cat
            log_fn(f"  + Categoría creada: {cdata['nombre']}")
        else:
            existing.nombre = cdata["nombre"]
            existing.descripcion = cdata["desc"]
            cat_map[cdata["slug"]] = existing
            log_fn(f"  = Categoría existente: {cdata['nombre']}")

    return cat_map


def seed_users(db, log_fn: Callable[[str], None] = print) -> list[User]:
    """Crea usuarios base iniciales (Admin, Vendedor, Cliente)."""
    users_data = [
        {
            "nombre": "German Rojas (Administrador)",
            "email": "rojascruzgermanlino@gmail.com",
            "password": "Password123!",
            "rol": Role.ADMIN,
            "telefono": "63014529",
            "direccion": "Av. Las Américas #780, Equipetrol, Santa Cruz",
        },
        {
            "nombre": "Admin DrapeMind",
            "email": "admin@drapemind.com",
            "password": "Admin12345!",
            "rol": Role.ADMIN,
            "telefono": "70011223",
            "direccion": "Calle 21 de Calacoto #1200, La Paz",
        },
        {
            "nombre": "Carlos Vendedor",
            "email": "vendedor@drapemind.com",
            "password": "Vendedor12345!",
            "rol": Role.VENDEDOR,
            "telefono": "71122334",
            "direccion": "Av. San Martín #450, Santa Cruz",
        },
        {
            "nombre": "Maria Cliente VIP",
            "email": "cliente@drapemind.com",
            "password": "Cliente12345!",
            "rol": Role.CLIENTE,
            "telefono": "72233445",
            "direccion": "Av. Ballivián #340, Cochabamba",
        },
    ]

    created = []
    for udata in users_data:
        user = db.scalar(select(User).where(func.lower(User.email) == udata["email"].lower()))
        if not user:
            user = User(
                nombre=udata["nombre"],
                email=udata["email"].lower(),
                password_hash=hash_password(udata["password"]),
                rol=udata["rol"],
                estado=UserStatus.ACTIVO,
                telefono=udata["telefono"],
            )
            db.add(user)
            db.flush()
            created.append(user)
            log_fn(f"  + Usuario creado: {udata['email']} [{udata['rol'].value}] (Pass: {udata['password']})")
        else:
            log_fn(f"  = Usuario existente: {udata['email']} [{user.rol.value}]")

        # Asegurar dirección principal para cada usuario
        addr = db.scalar(select(Address).where(Address.usuario_id == user.id))
        if not addr:
            addr = Address(
                usuario_id=user.id,
                alias="Dirección Principal",
                departamento="Santa Cruz",
                ciudad="Santa Cruz de la Sierra",
                zona="Centro / Equipetrol",
                direccion=udata["direccion"],
                telefono_contacto=udata["telefono"],
                es_principal=True,
            )
            db.add(addr)
            db.flush()
            log_fn(f"    - Dirección creada para: {user.email}")

    return created


def seed_products(db, cat_map: dict[str, Category], log_fn: Callable[[str], None] = print):
    """Crea un catálogo diverso y realista de productos (30+) con variantes de talla, color y stock."""
    products_data = [
        # POLERAS & CAMISETAS
        {
            "cat": "poleras-camisetas",
            "nombre": "Polera Básica Heavyweight Algodón Peruano",
            "marca": "Urban Draper",
            "material": "100% Algodón Peinado 240gsm",
            "precio": Decimal("119.00"),
            "costo": Decimal("45.00"),
            "calidad": 4,
            "genero": Gender.UNISEX,
            "desc": "Polera de corte regular con cuello acanalado reforzado y textura suave de alta durabilidad.",
            "desc_ai": "Prenda básica imprescindible, cómoda, transpirable y versátil para cualquier conjunto casual.",
            "tags_ai": ["polera", "camiseta", "basico", "casual", "algodon", "verano", "economico"],
            "variants": [
                {"sku": "POL-BAS-BLA-S", "color": "Blanco Puro", "codigo_color": "#FFFFFF", "talla": "S", "stock": 25},
                {"sku": "POL-BAS-BLA-M", "color": "Blanco Puro", "codigo_color": "#FFFFFF", "talla": "M", "stock": 35},
                {"sku": "POL-BAS-BLA-L", "color": "Blanco Puro", "codigo_color": "#FFFFFF", "talla": "L", "stock": 20},
                {"sku": "POL-BAS-NEG-M", "color": "Negro Profundo", "codigo_color": "#111111", "talla": "M", "stock": 40},
                {"sku": "POL-BAS-NEG-L", "color": "Negro Profundo", "codigo_color": "#111111", "talla": "L", "stock": 30},
                {"sku": "POL-BAS-BEI-M", "color": "Arena Cálido", "codigo_color": "#E3DAC9", "talla": "M", "stock": 20},
            ]
        },
        {
            "cat": "poleras-camisetas",
            "nombre": "Polera Oversize Minimalist Studio",
            "marca": "Drape Street",
            "material": "100% Algodón Orgánico Lavado",
            "precio": Decimal("149.00"),
            "costo": Decimal("60.00"),
            "calidad": 5,
            "genero": Gender.UNISEX,
            "desc": "Polera con hombros caídos y silueta holgada streetwear contemporánea.",
            "desc_ai": "Estilo relajado moderno, ideal para looks urbanos con jeans o joggers.",
            "tags_ai": ["polera", "oversize", "urbano", "streetwear", "moda", "cena", "casual", "comodo"],
            "variants": [
                {"sku": "POL-OVR-GRI-M", "color": "Gris Jaspe", "codigo_color": "#808080", "talla": "M", "stock": 22},
                {"sku": "POL-OVR-GRI-L", "color": "Gris Jaspe", "codigo_color": "#808080", "talla": "L", "stock": 25},
                {"sku": "POL-OVR-VER-M", "color": "Verde Salvia", "codigo_color": "#9EAA8F", "talla": "M", "stock": 18},
                {"sku": "POL-OVR-VER-L", "color": "Verde Salvia", "codigo_color": "#9EAA8F", "talla": "L", "stock": 15},
            ]
        },
        {
            "cat": "poleras-camisetas",
            "nombre": "Polo Piqué Clásico Cuello Mao",
            "marca": "Urban Draper",
            "material": "95% Algodón, 5% Elastano",
            "precio": Decimal("159.00"),
            "costo": Decimal("65.00"),
            "calidad": 4,
            "genero": Gender.HOMBRE,
            "desc": "Polo ligero con textura piqué y cuello estructurado moderno.",
            "desc_ai": "Prenda deportiva elegante ideal para días cálidos, cenas informales y fines de semana.",
            "tags_ai": ["polo", "polera", "casual", "verano", "cuello-mao", "comodo", "cena"],
            "variants": [
                {"sku": "POL-MAO-NEG-M", "color": "Negro Total", "codigo_color": "#000000", "talla": "M", "stock": 30},
                {"sku": "POL-MAO-NEG-L", "color": "Negro Total", "codigo_color": "#000000", "talla": "L", "stock": 22},
                {"sku": "POL-MAO-AZU-M", "color": "Azul Marino", "codigo_color": "#0B1D3A", "talla": "M", "stock": 20},
                {"sku": "POL-MAO-VER-M", "color": "Verde Oliva", "codigo_color": "#556B2F", "talla": "M", "stock": 15},
            ]
        },
        {
            "cat": "poleras-camisetas",
            "nombre": "Polera Gráfica Edición Limitada Atelier",
            "marca": "Drape Studio",
            "material": "100% Algodón Peinado",
            "precio": Decimal("179.00"),
            "costo": Decimal("70.00"),
            "calidad": 5,
            "genero": Gender.UNISEX,
            "desc": "Estampado serigráfico de arte botánico minimalista en la espalda y tipografía frontal.",
            "desc_ai": "Polera de diseño de autor para quienes buscan distinción en conjuntos informales.",
            "tags_ai": ["polera", "grafica", "diseno", "exclusivo", "casual", "verano"],
            "variants": [
                {"sku": "POL-GRA-BLA-M", "color": "Blanco Crudo", "codigo_color": "#FDFBF7", "talla": "M", "stock": 18},
                {"sku": "POL-GRA-BLA-L", "color": "Blanco Crudo", "codigo_color": "#FDFBF7", "talla": "L", "stock": 14},
                {"sku": "POL-GRA-NEG-L", "color": "Negro Lavado", "codigo_color": "#2A2A2A", "talla": "L", "stock": 16},
            ]
        },

        # CAMISAS & BLUSAS
        {
            "cat": "camisas-blusas",
            "nombre": "Camisa Oxford Slim Fit Algodón Pima",
            "marca": "Drape Studio",
            "material": "100% Algodón Pima Peruano",
            "precio": Decimal("249.00"),
            "costo": Decimal("110.00"),
            "calidad": 5,
            "genero": Gender.HOMBRE,
            "desc": "Camisa de vestir formal y casual, tejido suave y transpirable de alta durabilidad.",
            "desc_ai": "Camisa clásica elegante de tono versátil para oficina, cenas formales o eventos smart-casual.",
            "tags_ai": ["camisa", "formal", "oficina", "algodon", "slim-fit", "atemporal", "cena", "elegante"],
            "variants": [
                {"sku": "CAM-OXF-BLA-S", "color": "Blanco", "codigo_color": "#FFFFFF", "talla": "S", "stock": 15},
                {"sku": "CAM-OXF-BLA-M", "color": "Blanco", "codigo_color": "#FFFFFF", "talla": "M", "stock": 25},
                {"sku": "CAM-OXF-BLA-L", "color": "Blanco", "codigo_color": "#FFFFFF", "talla": "L", "stock": 20},
                {"sku": "CAM-OXF-AZU-M", "color": "Azul Cielo", "codigo_color": "#87CEEB", "talla": "M", "stock": 18},
                {"sku": "CAM-OXF-AZU-L", "color": "Azul Cielo", "codigo_color": "#87CEEB", "talla": "L", "stock": 14},
            ]
        },
        {
            "cat": "camisas-blusas",
            "nombre": "Camisa de Lino Fresco Manga Larga",
            "marca": "Linen & Co",
            "material": "100% Lino Natural Europeo",
            "precio": Decimal("299.00"),
            "costo": Decimal("130.00"),
            "calidad": 5,
            "genero": Gender.UNISEX,
            "desc": "Camisa ligera y transpirable, corte relajado con botones de nácar natural.",
            "desc_ai": "Ideal para climas cálidos, cenas al aire libre y eventos casual-chic de verano.",
            "tags_ai": ["camisa", "lino", "verano", "fresco", "elegante", "cena", "casual-chic"],
            "variants": [
                {"sku": "CAM-LIN-BEI-S", "color": "Lino Natural", "codigo_color": "#E6DEC8", "talla": "S", "stock": 12},
                {"sku": "CAM-LIN-BEI-M", "color": "Lino Natural", "codigo_color": "#E6DEC8", "talla": "M", "stock": 20},
                {"sku": "CAM-LIN-BEI-L", "color": "Lino Natural", "codigo_color": "#E6DEC8", "talla": "L", "stock": 15},
                {"sku": "CAM-LIN-BLA-M", "color": "Blanco Nieve", "codigo_color": "#FFFFFF", "talla": "M", "stock": 18},
            ]
        },
        {
            "cat": "camisas-blusas",
            "nombre": "Blusa Seda Satinada Cuello Halter",
            "marca": "Aura Elegance",
            "material": "Seda Satén y Elastano",
            "precio": Decimal("289.00"),
            "costo": Decimal("120.00"),
            "calidad": 5,
            "genero": Gender.MUJER,
            "desc": "Blusa fluida con brillo sutil, espalda descubierta y lazo elegante al cuello.",
            "desc_ai": "Perfecta para cenas románticas, cócteles nocturnos y eventos de gala.",
            "tags_ai": ["blusa", "seda", "saten", "fiesta", "cena", "elegante", "gala", "mujer"],
            "variants": [
                {"sku": "BLU-SED-NEG-S", "color": "Negro Satinado", "codigo_color": "#1A1A1A", "talla": "S", "stock": 10},
                {"sku": "BLU-SED-NEG-M", "color": "Negro Satinado", "codigo_color": "#1A1A1A", "talla": "M", "stock": 15},
                {"sku": "BLU-SED-CHA-M", "color": "Champagne", "codigo_color": "#F7E7CE", "talla": "M", "stock": 12},
            ]
        },

        # PANTALONES & JEANS
        {
            "cat": "pantalones-jeans",
            "nombre": "Jeans Straight Fit Denim Indigo",
            "marca": "Drape Denim",
            "material": "98% Algodón, 2% Spandex",
            "precio": Decimal("289.00"),
            "costo": Decimal("130.00"),
            "calidad": 4,
            "genero": Gender.HOMBRE,
            "desc": "Pantalón vaquero de corte recto con lavado índigo profundo y ligero stretch.",
            "desc_ai": "Jean versátil de alta resistencia para combinar con camisas, blazers o poleras en cenas y salidas.",
            "tags_ai": ["denim", "jeans", "pantalon", "casual", "resistente", "cena", "versatil"],
            "variants": [
                {"sku": "JEA-STR-IND-30", "color": "Índigo Oscuro", "codigo_color": "#1A2B4C", "talla": "30", "stock": 15},
                {"sku": "JEA-STR-IND-32", "color": "Índigo Oscuro", "codigo_color": "#1A2B4C", "talla": "32", "stock": 25},
                {"sku": "JEA-STR-IND-34", "color": "Índigo Oscuro", "codigo_color": "#1A2B4C", "talla": "34", "stock": 18},
                {"sku": "JEA-STR-NEG-32", "color": "Negro Lavado", "codigo_color": "#2B2B2B", "talla": "32", "stock": 20},
            ]
        },
        {
            "cat": "pantalones-jeans",
            "nombre": "Pantalón Chino Comfort Fit",
            "marca": "Drape Studio",
            "material": "Gabardina Premium 100% Algodón",
            "precio": Decimal("239.00"),
            "costo": Decimal("100.00"),
            "calidad": 4,
            "genero": Gender.HOMBRE,
            "desc": "Pantalón tipo chino elegante de estilo semi-formal con acabado peinado.",
            "desc_ai": "Chino beige clásico para estilismos smart-casual ejecutivos y cenas relajadas.",
            "tags_ai": ["chino", "pantalon", "formal", "beige", "oficina", "cena", "smart-casual"],
            "variants": [
                {"sku": "CHI-BEI-30", "color": "Beige Arena", "codigo_color": "#E1C699", "talla": "30", "stock": 14},
                {"sku": "CHI-BEI-32", "color": "Beige Arena", "codigo_color": "#E1C699", "talla": "32", "stock": 22},
                {"sku": "CHI-MAR-32", "color": "Azul Marino", "codigo_color": "#000080", "talla": "32", "stock": 18},
                {"sku": "CHI-VER-32", "color": "Verde Oliva", "codigo_color": "#556B2F", "talla": "32", "stock": 12},
            ]
        },
        {
            "cat": "pantalones-jeans",
            "nombre": "Pantalón Palazzo Sastrero Fluido",
            "marca": "Aura Elegance",
            "material": "Crepe de Lana y Viscosa",
            "precio": Decimal("319.00"),
            "costo": Decimal("140.00"),
            "calidad": 5,
            "genero": Gender.MUJER,
            "desc": "Pantalón de tiro alto y pierna ancha con pinzas frontales refinadas.",
            "desc_ai": "Elegancia sofisticada para reuniones ejecutivas, eventos formales o cenas de gala.",
            "tags_ai": ["palazzo", "pantalon", "sastreria", "elegante", "formal", "mujer", "cena"],
            "variants": [
                {"sku": "PAL-SAS-NEG-S", "color": "Negro Azabache", "codigo_color": "#0F0F0F", "talla": "S", "stock": 10},
                {"sku": "PAL-SAS-NEG-M", "color": "Negro Azabache", "codigo_color": "#0F0F0F", "talla": "M", "stock": 16},
                {"sku": "PAL-SAS-MAR-M", "color": "Marfil", "codigo_color": "#FFFFF0", "talla": "M", "stock": 12},
            ]
        },
        {
            "cat": "pantalones-jeans",
            "nombre": "Joggers Urban Cargo con Ajuste Cónico",
            "marca": "Street Luxe",
            "material": "Algodón Ripstop y Spandex",
            "precio": Decimal("199.00"),
            "costo": Decimal("85.00"),
            "calidad": 4,
            "genero": Gender.UNISEX,
            "desc": "Pantalón jogger con múltiples bolsillos funcionales y cintura elastizada con cordón.",
            "desc_ai": "Estilo urbano utilitario ultra cómodo para el día a día y viajes.",
            "tags_ai": ["jogger", "cargo", "pantalon", "urbano", "streetwear", "comodo", "economico"],
            "variants": [
                {"sku": "JOG-CAR-NEG-M", "color": "Negro", "codigo_color": "#111111", "talla": "M", "stock": 25},
                {"sku": "JOG-CAR-NEG-L", "color": "Negro", "codigo_color": "#111111", "talla": "L", "stock": 20},
                {"sku": "JOG-CAR-VER-M", "color": "Verde Militar", "codigo_color": "#4B5320", "talla": "M", "stock": 18},
            ]
        },

        # VESTIDOS & FALDAS
        {
            "cat": "vestidos-faldas",
            "nombre": "Vestido Midi Seda Floral Botánico",
            "marca": "Aura Elegance",
            "material": "Seda Satén y Viscosa",
            "precio": Decimal("399.00"),
            "costo": Decimal("180.00"),
            "calidad": 5,
            "genero": Gender.MUJER,
            "desc": "Vestido midi con caída fluida, escote en V y estampado botánico elegante.",
            "desc_ai": "Vestido sofisticado para cócteles, bodas de día y cenas formales.",
            "tags_ai": ["vestido", "elegante", "seda", "fiesta", "estampado", "cena", "boda"],
            "variants": [
                {"sku": "VES-MID-FLO-S", "color": "Floral Marino", "codigo_color": "#2C3E50", "talla": "S", "stock": 8},
                {"sku": "VES-MID-FLO-M", "color": "Floral Marino", "codigo_color": "#2C3E50", "talla": "M", "stock": 14},
                {"sku": "VES-MID-BUR-M", "color": "Rojo Borgoña", "codigo_color": "#800020", "talla": "M", "stock": 10},
            ]
        },
        {
            "cat": "vestidos-faldas",
            "nombre": "Little Black Dress de Cóctel Clásico",
            "marca": "Aura Elegance",
            "material": "Punto Milano Estructurado",
            "precio": Decimal("349.00"),
            "costo": Decimal("150.00"),
            "calidad": 5,
            "genero": Gender.MUJER,
            "desc": "El infaltable vestido negro entallado con largo a la rodilla y escote barco.",
            "desc_ai": "Pieza icónica y atemporal para eventos nocturnos, cenas elegantes y celebraciones.",
            "tags_ai": ["vestido", "negro", "coctel", "cena", "elegante", "noche", "clasico"],
            "variants": [
                {"sku": "VES-LBD-NEG-XS", "color": "Negro", "codigo_color": "#000000", "talla": "XS", "stock": 6},
                {"sku": "VES-LBD-NEG-S", "color": "Negro", "codigo_color": "#000000", "talla": "S", "stock": 12},
                {"sku": "VES-LBD-NEG-M", "color": "Negro", "codigo_color": "#000000", "talla": "M", "stock": 15},
            ]
        },
        {
            "cat": "vestidos-faldas",
            "nombre": "Falda Plisada Midi Satén Brillante",
            "marca": "Aura Elegance",
            "material": "Satén de Poliéster Reciclado Premium",
            "precio": Decimal("219.00"),
            "costo": Decimal("90.00"),
            "calidad": 4,
            "genero": Gender.MUJER,
            "desc": "Falda midi plisada con cintura elástica dorada y hermoso movimiento al caminar.",
            "desc_ai": "Prenda dinámica que combina perfecto con botas, sandalias o zapatillas blancas.",
            "tags_ai": ["falda", "plisada", "midi", "saten", "fiesta", "casual-chic", "cena"],
            "variants": [
                {"sku": "FAL-PLI-DOR-S", "color": "Oro Suave", "codigo_color": "#D4AF37", "talla": "S", "stock": 10},
                {"sku": "FAL-PLI-DOR-M", "color": "Oro Suave", "codigo_color": "#D4AF37", "talla": "M", "stock": 15},
                {"sku": "FAL-PLI-NEG-M", "color": "Negro Noche", "codigo_color": "#111111", "talla": "M", "stock": 12},
            ]
        },

        # CHAQUETAS & ABRIGOS
        {
            "cat": "chaquetas-abrigos",
            "nombre": "Blazer Ejecutivo Lana Merino",
            "marca": "Tailor Crafted",
            "material": "100% Lana Merino Fina",
            "precio": Decimal("599.00"),
            "costo": Decimal("260.00"),
            "calidad": 5,
            "genero": Gender.UNISEX,
            "desc": "Blazer estructurado con forro de acetato, hombreras suaves y solapa clásica.",
            "desc_ai": "Pieza clave de sastrería para conjuntos ejecutivos, cenas formales y eventos de alto nivel.",
            "tags_ai": ["blazer", "saco", "formal", "lana", "premium", "cena", "oficina", "elegante"],
            "variants": [
                {"sku": "BLA-MER-GRI-38", "color": "Gris Marengo", "codigo_color": "#4A4A4A", "talla": "38", "stock": 8},
                {"sku": "BLA-MER-GRI-40", "color": "Gris Marengo", "codigo_color": "#4A4A4A", "talla": "40", "stock": 12},
                {"sku": "BLA-MER-AZU-40", "color": "Azul Noche", "codigo_color": "#0B132B", "talla": "40", "stock": 10},
                {"sku": "BLA-MER-NEG-40", "color": "Negro Smoking", "codigo_color": "#0A0A0A", "talla": "40", "stock": 14},
            ]
        },
        {
            "cat": "chaquetas-abrigos",
            "nombre": "Chamarra Biker Cuero Genuino",
            "marca": "Street Luxe",
            "material": "100% Cuero Vacuno Grano Entero",
            "precio": Decimal("689.00"),
            "costo": Decimal("300.00"),
            "calidad": 5,
            "genero": Gender.UNISEX,
            "desc": "Chamarra de motociclista icónica con cremalleras metálicas YKK y forro térmico acolchado.",
            "desc_ai": "Añade actitud y carácter premium a cualquier atuendo casual nocturno.",
            "tags_ai": ["cuero", "chamarra", "chaqueta", "biker", "rock", "streetwear", "cena", "invierno"],
            "variants": [
                {"sku": "CHA-BIK-NEG-S", "color": "Negro Mate", "codigo_color": "#1C1C1C", "talla": "S", "stock": 6},
                {"sku": "CHA-BIK-NEG-M", "color": "Negro Mate", "codigo_color": "#1C1C1C", "talla": "M", "stock": 10},
                {"sku": "CHA-BIK-NEG-L", "color": "Negro Mate", "codigo_color": "#1C1C1C", "talla": "L", "stock": 8},
            ]
        },
        {
            "cat": "chaquetas-abrigos",
            "nombre": "Bomber Jacket Ligera Impermeable",
            "marca": "Urban Draper",
            "material": "Nylon Ripstop con Revestimiento DWR",
            "precio": Decimal("279.00"),
            "costo": Decimal("110.00"),
            "calidad": 4,
            "genero": Gender.UNISEX,
            "desc": "Chaqueta bomber ligera ideal para media estación y protección contra viento y llovizna.",
            "desc_ai": "Chaqueta casual moderna que combina perfectamente con poleras y jeans.",
            "tags_ai": ["bomber", "chaqueta", "casual", "urbano", "impermeable", "economico"],
            "variants": [
                {"sku": "BOM-LIG-VER-M", "color": "Verde Militar", "codigo_color": "#4B5320", "talla": "M", "stock": 15},
                {"sku": "BOM-LIG-VER-L", "color": "Verde Militar", "codigo_color": "#4B5320", "talla": "L", "stock": 18},
                {"sku": "BOM-LIG-NEG-M", "color": "Negro", "codigo_color": "#111111", "talla": "M", "stock": 20},
            ]
        },
        {
            "cat": "chaquetas-abrigos",
            "nombre": "Gabardina Trench Coat Clásica",
            "marca": "Tailor Crafted",
            "material": "Gabardina de Algodón Impermeabilizado",
            "precio": Decimal("549.00"),
            "costo": Decimal("230.00"),
            "calidad": 5,
            "genero": Gender.UNISEX,
            "desc": "Trench coat cruzado con cinturón de hebilla, charreteras y forro tartán clásico.",
            "desc_ai": "Elegancia británica atemporal para días lluviosos y outfits ejecutivos.",
            "tags_ai": ["trench", "gabardina", "abrigo", "elegante", "formal", "clasico"],
            "variants": [
                {"sku": "TRE-CLA-BEI-M", "color": "Beige Camel", "codigo_color": "#C19A6B", "talla": "M", "stock": 10},
                {"sku": "TRE-CLA-BEI-L", "color": "Beige Camel", "codigo_color": "#C19A6B", "talla": "L", "stock": 8},
            ]
        },

        # CALZADO & ZAPATOS
        {
            "cat": "calzado-zapatos",
            "nombre": "Zapatillas Urbanas Cuero Nappa Blanco",
            "marca": "Street Luxe",
            "material": "Cuero vacuno genuino y suela de caucho vulcanizado",
            "precio": Decimal("349.00"),
            "costo": Decimal("150.00"),
            "calidad": 5,
            "genero": Gender.UNISEX,
            "desc": "Zapatillas minimalistas de perfil bajo con plantilla ergonómica de espuma viscoelástica.",
            "desc_ai": "Sneakers blancas versátiles que combinan con trajes formales, jeans, vestidos o shorts.",
            "tags_ai": ["zapatillas", "sneakers", "calzado", "cuero", "blanco", "urbano", "cena", "comodo"],
            "variants": [
                {"sku": "SNE-NAP-BLA-39", "color": "Blanco Puro", "codigo_color": "#FFFFFF", "talla": "39", "stock": 10},
                {"sku": "SNE-NAP-BLA-40", "color": "Blanco Puro", "codigo_color": "#FFFFFF", "talla": "40", "stock": 16},
                {"sku": "SNE-NAP-BLA-41", "color": "Blanco Puro", "codigo_color": "#FFFFFF", "talla": "41", "stock": 20},
                {"sku": "SNE-NAP-BLA-42", "color": "Blanco Puro", "codigo_color": "#FFFFFF", "talla": "42", "stock": 15},
                {"sku": "SNE-NAP-NEG-41", "color": "Negro Total", "codigo_color": "#111111", "talla": "41", "stock": 12},
            ]
        },
        {
            "cat": "calzado-zapatos",
            "nombre": "Zapatos Oxford Formales Artesanales",
            "marca": "Tailor Crafted",
            "material": "100% Cuero Box Calf y Suela de Cuero Cosido Goodyear",
            "precio": Decimal("499.00"),
            "costo": Decimal("220.00"),
            "calidad": 5,
            "genero": Gender.HOMBRE,
            "desc": "Calzado formal por excelencia con puntera lisa y acabado abrillantado a mano.",
            "desc_ai": "Zapato de gala imprescindible para trajes ejecutivos, matrimonios y cenas formales.",
            "tags_ai": ["zapatos", "oxford", "formal", "calzado", "cuero", "elegante", "cena", "gala"],
            "variants": [
                {"sku": "ZAP-OXF-NEG-40", "color": "Negro Espejo", "codigo_color": "#0D0D0D", "talla": "40", "stock": 8},
                {"sku": "ZAP-OXF-NEG-41", "color": "Negro Espejo", "codigo_color": "#0D0D0D", "talla": "41", "stock": 12},
                {"sku": "ZAP-OXF-CAF-41", "color": "Café Coñac", "codigo_color": "#6E3B1F", "talla": "41", "stock": 10},
            ]
        },
        {
            "cat": "calzado-zapatos",
            "nombre": "Botas Chelsea Cuero Gamuzado",
            "marca": "Urban Draper",
            "material": "Cuero Nobuk Gamuzado y Elásticos Reforzados",
            "precio": Decimal("389.00"),
            "costo": Decimal("170.00"),
            "calidad": 4,
            "genero": Gender.UNISEX,
            "desc": "Botas al tobillo sin cordones con tirador trasero y suela antideslizante.",
            "desc_ai": "Estilo refinado y atrevido para conjuntos de otoño/invierno con jeans o chinos.",
            "tags_ai": ["botas", "chelsea", "calzado", "gamusa", "cena", "casual-chic"],
            "variants": [
                {"sku": "BOT-CHE-HAB-40", "color": "Habano", "codigo_color": "#704214", "talla": "40", "stock": 8},
                {"sku": "BOT-CHE-HAB-41", "color": "Habano", "codigo_color": "#704214", "talla": "41", "stock": 14},
                {"sku": "BOT-CHE-NEG-41", "color": "Negro", "codigo_color": "#1A1A1A", "talla": "41", "stock": 10},
            ]
        },
        {
            "cat": "calzado-zapatos",
            "nombre": "Mocasines Loafer Cuero con Hebilla",
            "marca": "Tailor Crafted",
            "material": "Cuero Florentic Italiano",
            "precio": Decimal("429.00"),
            "costo": Decimal("190.00"),
            "calidad": 5,
            "genero": Gender.UNISEX,
            "desc": "Mocasín estilo Penny Loafer con detalle metálico dorado y suela flexible.",
            "desc_ai": "Calzado smart-casual cómodo y distinguido para oficina o salidas gourmet.",
            "tags_ai": ["mocasines", "loafer", "zapatos", "calzado", "cuero", "cena", "elegante"],
            "variants": [
                {"sku": "MOC-LOA-BUR-40", "color": "Vino Tinto", "codigo_color": "#5E1914", "talla": "40", "stock": 7},
                {"sku": "MOC-LOA-BUR-41", "color": "Vino Tinto", "codigo_color": "#5E1914", "talla": "41", "stock": 10},
                {"sku": "MOC-LOA-NEG-41", "color": "Negro", "codigo_color": "#111111", "talla": "41", "stock": 12},
            ]
        },

        # ACCESORIOS & BOLSOS
        {
            "cat": "accesorios-bolsos",
            "nombre": "Cinturón de Cuero Reversible Clásico",
            "marca": "Drape Leather",
            "material": "100% Cuero Genuino con hebilla de acero pulido",
            "precio": Decimal("129.00"),
            "costo": Decimal("45.00"),
            "calidad": 4,
            "genero": Gender.UNISEX,
            "desc": "Cinturón reversible café/negro con hebilla rotatoria de ajuste milimétrico.",
            "desc_ai": "Accesorio esencial 2 en 1 para combinar calzado y trajes de vestir.",
            "tags_ai": ["cinturon", "cuero", "accesorio", "reversible", "cena", "economico"],
            "variants": [
                {"sku": "CIN-REV-90", "color": "Negro / Café", "codigo_color": "#3B2F2F", "talla": "90 cm", "stock": 25},
                {"sku": "CIN-REV-100", "color": "Negro / Café", "codigo_color": "#3B2F2F", "talla": "100 cm", "stock": 30},
                {"sku": "CIN-REV-110", "color": "Negro / Café", "codigo_color": "#3B2F2F", "talla": "110 cm", "stock": 20},
            ]
        },
        {
            "cat": "accesorios-bolsos",
            "nombre": "Bolso Tote Bag Cuero Vacuno Minimal",
            "marca": "Drape Leather",
            "material": "Cuero Rústico Encerado",
            "precio": Decimal("389.00"),
            "costo": Decimal("160.00"),
            "calidad": 5,
            "genero": Gender.UNISEX,
            "desc": "Bolso amplio con compartimento para laptop de 15 pulgadas y bolsillo interno con cierre.",
            "desc_ai": "Bolso espacioso y elegante para profesionales, estudiantes y uso diario.",
            "tags_ai": ["bolso", "tote", "cuero", "accesorio", "oficina", "mujer", "unisex"],
            "variants": [
                {"sku": "BOL-TOT-CAR-U", "color": "Caramelo", "codigo_color": "#8B5A2B", "talla": "Única", "stock": 15},
                {"sku": "BOL-TOT-NEG-U", "color": "Negro Mate", "codigo_color": "#1C1C1C", "talla": "Única", "stock": 18},
            ]
        },
        {
            "cat": "accesorios-bolsos",
            "nombre": "Bufanda de Lana y Cachemira Suave",
            "marca": "Tailor Crafted",
            "material": "70% Lana Merino, 30% Cachemira",
            "precio": Decimal("169.00"),
            "costo": Decimal("65.00"),
            "calidad": 5,
            "genero": Gender.UNISEX,
            "desc": "Bufanda tejida con flecos tradicionales, tacto ultrasuave y abrigo térmico liviano.",
            "desc_ai": "El complemento ideal para sacos, sobretodos y abrigos de invierno.",
            "tags_ai": ["bufanda", "lana", "cachemira", "invierno", "accesorio", "elegante", "cena"],
            "variants": [
                {"sku": "BUF-CAC-GRI-U", "color": "Gris Perla", "codigo_color": "#C0C0C0", "talla": "Única", "stock": 20},
                {"sku": "BUF-CAC-BUR-U", "color": "Burdeos", "codigo_color": "#800020", "talla": "Única", "stock": 15},
            ]
        },
        {
            "cat": "accesorios-bolsos",
            "nombre": "Reloj de Pulsera Minimalist Steel",
            "marca": "Drape Timepiece",
            "material": "Caja de Acero Inoxidable 316L y Cristal de Zafiro",
            "precio": Decimal("449.00"),
            "costo": Decimal("180.00"),
            "calidad": 5,
            "genero": Gender.UNISEX,
            "desc": "Reloj analógico con esfera limpia, correa de malla milanesa ajustable y resistencia al agua 5ATM.",
            "desc_ai": "Accesorio de lujo accesible que corona cualquier conjunto formal o casual.",
            "tags_ai": ["reloj", "acero", "accesorio", "joyeria", "elegante", "cena", "regalo"],
            "variants": [
                {"sku": "REL-MIN-PLA-U", "color": "Plata Pulido", "codigo_color": "#E5E5E5", "talla": "Única", "stock": 12},
                {"sku": "REL-MIN-NEG-U", "color": "Negro Carbón", "codigo_color": "#222222", "talla": "Única", "stock": 14},
            ]
        },
        {
            "cat": "accesorios-bolsos",
            "nombre": "Lentes de Sol Aviador Polarizados",
            "marca": "Street Luxe",
            "material": "Marco de Titanio Ligero y Lentes UV400",
            "precio": Decimal("189.00"),
            "costo": Decimal("70.00"),
            "calidad": 4,
            "genero": Gender.UNISEX,
            "desc": "Gafas de sol polarizadas de silueta clásica aviador con almohadillas nasales de silicona.",
            "desc_ai": "Protección solar y estilo atemporal para días soleados y paseos urbanos.",
            "tags_ai": ["lentes", "gafas", "sol", "accesorio", "verano", "casual"],
            "variants": [
                {"sku": "LEN-AVI-DOR-U", "color": "Dorado / Verde", "codigo_color": "#D4AF37", "talla": "Única", "stock": 20},
                {"sku": "LEN-AVI-NEG-U", "color": "Negro Total", "codigo_color": "#111111", "talla": "Única", "stock": 25},
            ]
        },

        # DEPORTES & ATHLEISURE
        {
            "cat": "deportes-athleisure",
            "nombre": "Hoodie Térmico French Terry",
            "marca": "Urban Draper",
            "material": "80% Algodón, 20% Poliéster Reciclado",
            "precio": Decimal("229.00"),
            "costo": Decimal("95.00"),
            "calidad": 4,
            "genero": Gender.UNISEX,
            "desc": "Sudadera con capucha forrada, bolsillo canguro y tejido afelpado de alta densidad.",
            "desc_ai": "Máxima comodidad para días frescos, gimnasio o descanso en casa.",
            "tags_ai": ["hoodie", "sudadera", "deportivo", "comodo", "casual", "athleisure"],
            "variants": [
                {"sku": "HOO-TER-GRI-M", "color": "Gris Jaspeado", "codigo_color": "#7E827A", "talla": "M", "stock": 20},
                {"sku": "HOO-TER-GRI-L", "color": "Gris Jaspeado", "codigo_color": "#7E827A", "talla": "L", "stock": 25},
                {"sku": "HOO-TER-NEG-M", "color": "Negro", "codigo_color": "#111111", "talla": "M", "stock": 22},
            ]
        },
    ]

    prod_count = 0
    variant_count = 0

    for pdata in products_data:
        cat = cat_map.get(pdata["cat"])
        if not cat:
            continue

        p = db.scalar(select(Product).where(Product.nombre == pdata["nombre"]))
        if not p:
            p = Product(
                categoria_id=cat.id,
                nombre=pdata["nombre"],
                marca=pdata["marca"],
                material=pdata["material"],
                precio=pdata["precio"],
                costo_referencia=pdata["costo"],
                calidad_nivel=pdata["calidad"],
                genero_objetivo=pdata["genero"],
                descripcion=pdata["desc"],
                descripcion_ai=pdata["desc_ai"],
                tags_ai=pdata["tags_ai"],
                imagenes=["/static/products/sample1.jpg"],
                activo=True,
            )
            db.add(p)
            db.flush()
            prod_count += 1
            log_fn(f"  + Producto creado: {p.nombre} (Bs. {p.precio})")
        else:
            p.categoria_id = cat.id
            p.marca = pdata["marca"]
            p.material = pdata["material"]
            p.precio = pdata["precio"]
            p.costo_referencia = pdata["costo"]
            p.calidad_nivel = pdata["calidad"]
            p.genero_objetivo = pdata["genero"]
            p.descripcion = pdata["desc"]
            p.descripcion_ai = pdata["desc_ai"]
            p.tags_ai = pdata["tags_ai"]
            p.activo = True
            log_fn(f"  = Producto actualizado: {p.nombre}")

        for vdata in pdata["variants"]:
            v = db.scalar(select(ProductVariant).where(ProductVariant.sku == vdata["sku"]))
            if not v:
                v = ProductVariant(
                    producto_id=p.id,
                    sku=vdata["sku"],
                    color=vdata["color"],
                    codigo_color=vdata.get("codigo_color"),
                    talla=vdata["talla"],
                    stock_total=vdata["stock"],
                    stock_reservado=0,
                    activo=True,
                )
                db.add(v)
                variant_count += 1
                log_fn(f"    - Variante SKU: {v.sku} [{v.color} | Talla {v.talla}] Stock: {v.stock_total}")
            else:
                v.stock_total = max(v.stock_total, vdata["stock"])
                v.color = vdata["color"]
                v.codigo_color = vdata.get("codigo_color")
                v.talla = vdata["talla"]
                v.activo = True

    log_fn(f"✨ Seeding completado: catálogo con {len(products_data)} productos configurados.")


def run_full_seed(log_fn: Callable[[str], None] = print):
    """Ejecuta el seeding completo de toda la base de datos."""
    log_fn("🌱 Iniciando Seeding Extendido de DrapeMind...")
    with SessionLocal() as db:
        log_fn("\n📁 1. Creando Categorías...")
        cat_map = seed_categories(db, log_fn)

        log_fn("\n👥 2. Creando Usuarios y Direcciones Base...")
        seed_users(db, log_fn)

        log_fn("\n👔 3. Creando Catálogo Extenso de Productos y Variantes...")
        seed_products(db, cat_map, log_fn)

        db.commit()
    log_fn("\n🎉 ¡Base de datos de DrapeMind sembrada y actualizada exitosamente!")


if __name__ == "__main__":
    run_full_seed()
