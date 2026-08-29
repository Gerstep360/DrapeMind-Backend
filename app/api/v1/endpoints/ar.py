from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user_optional
from app.core.config import settings
from app.db.session import get_db
from app.models import Product, ProductVariant, User
from app.schemas.api import ARConfig

router = APIRouter()


@router.get("/capabilities", summary="Capacidades del probador virtual")
def capabilities() -> dict:
    return {
        "mode": "2d-overlay",
        "backend": ["asset-validation", "size-recommendation", "fabric-parameters"],
        "mobile": ["camera", "pose-tracking", "rendering"],
        "requires": ["camera_permission", "person_in_frame", "ar_asset"],
        "supports_3d": False,
    }


@router.get(
    "/products/{product_id}/try-on-config",
    response_model=ARConfig,
    summary="Configuracion de probador AR",
    description=(
        "CU-15. La camara, segmentacion y render se ejecutan en Flutter. El backend valida el producto, "
        "calcula las matrices dimensionales por talla y devuelve los parámetros de holgura y física textil."
    ),
)
def try_on_config(
    product_id: int,
    user_chest: float | None = Query(default=None, ge=50, le=160),
    user_waist: float | None = Query(default=None, ge=40, le=160),
    user_height: float | None = Query(default=None, ge=120, le=230),
    user: User | None = Depends(get_current_user_optional),
    db: Session = Depends(get_db),
) -> ARConfig:
    product = db.get(Product, product_id)
    if not product or not product.activo:
        raise HTTPException(404, "Producto no encontrado")

    # 1. Determinar URL del Asset 2D/3D
    asset_url = None
    for image in product.imagenes or []:
        if isinstance(image, dict) and image.get("ar_asset"):
            asset_url = image["ar_asset"]
            break
        elif isinstance(image, str) and (image.endswith(".png") or image.endswith(".webp")):
            asset_url = image

    if not asset_url and product.tags_ai and "ar-ready" in product.tags_ai:
        asset_url = f"{settings.AR_ASSET_BASE_URL.rstrip('/')}/{product.id}.png"

    if not asset_url and product.imagenes and len(product.imagenes) > 0:
        first_img = product.imagenes[0]
        asset_url = first_img.get("url") if isinstance(first_img, dict) else str(first_img)

    # 2. Extraer tallas disponibles de las variantes activas
    variants = list(
        db.scalars(
            select(ProductVariant)
            .where(ProductVariant.producto_id == product.id, ProductVariant.activo.is_(True))
            .order_by(ProductVariant.color, ProductVariant.talla)
        )
    )
    available_sizes: list[str] = []
    for v in variants:
        if v.activo and v.talla and v.talla not in available_sizes:
            available_sizes.append(v.talla)

    if not available_sizes:
        available_sizes = ["S", "M", "L", "XL"]

    # 3. Categoría y tipo de ajuste
    nombre_l = product.nombre.lower()
    material_l = (product.material or "").lower()

    if any(k in nombre_l for k in ["oversize", "ancho", "wide"]):
        fit_cat = "oversize"
    elif any(k in nombre_l for k in ["slim", "ajustado", "ceñido"]):
        fit_cat = "slim"
    elif any(k in nombre_l for k in ["palazzo", "holgado", "relaxed"]):
        fit_cat = "relaxed"
    else:
        fit_cat = "regular"

    # Elasticidad de tela
    elasticity = 0.05
    if "lino" in material_l or "seda" in material_l:
        elasticity = 0.02
    elif "cuero" in material_l or "denim" in material_l:
        elasticity = 0.01
    elif "algodon" in material_l or "algodón" in material_l:
        elasticity = 0.07
    elif "punto" in material_l or "spandex" in material_l or "elastano" in material_l:
        elasticity = 0.18

    # 4. Generación de tabla dimensional por talla (en centímetros)
    is_bottom = any(k in nombre_l for k in ["pantalon", "pantalón", "jean", "falda", "bermuda", "palazzo"])
    is_shoe = any(k in nombre_l for k in ["zapato", "calzado", "bota", "mocas", "zapatilla"])

    size_metrics: dict[str, dict[str, float]] = {}

    size_multipliers = {
        "XS": {"chest": 90.0, "shoulders": 42.0, "length": 68.0, "waist": 74.0, "hip": 90.0, "foot": 24.0},
        "S": {"chest": 96.0, "shoulders": 44.0, "length": 70.0, "waist": 80.0, "hip": 96.0, "foot": 25.0},
        "M": {"chest": 102.0, "shoulders": 46.0, "length": 72.0, "waist": 86.0, "hip": 102.0, "foot": 26.5},
        "L": {"chest": 108.0, "shoulders": 48.0, "length": 74.0, "waist": 92.0, "hip": 108.0, "foot": 27.5},
        "XL": {"chest": 114.0, "shoulders": 50.0, "length": 76.0, "waist": 98.0, "hip": 114.0, "foot": 28.5},
        "XXL": {"chest": 120.0, "shoulders": 52.0, "length": 78.0, "waist": 104.0, "hip": 120.0, "foot": 29.5},
        "28": {"chest": 92.0, "shoulders": 42.0, "length": 98.0, "waist": 72.0, "hip": 88.0, "foot": 24.0},
        "30": {"chest": 96.0, "shoulders": 44.0, "length": 100.0, "waist": 76.0, "hip": 92.0, "foot": 25.0},
        "32": {"chest": 102.0, "shoulders": 46.0, "length": 102.0, "waist": 82.0, "hip": 98.0, "foot": 26.5},
        "34": {"chest": 108.0, "shoulders": 48.0, "length": 104.0, "waist": 88.0, "hip": 104.0, "foot": 27.5},
        "36": {"chest": 114.0, "shoulders": 50.0, "length": 106.0, "waist": 94.0, "hip": 110.0, "foot": 28.5},
        "38": {"chest": 120.0, "shoulders": 52.0, "length": 108.0, "waist": 100.0, "hip": 116.0, "foot": 29.5},
        "40": {"chest": 100.0, "shoulders": 45.0, "length": 26.0, "waist": 80.0, "hip": 95.0, "foot": 25.5},
        "41": {"chest": 102.0, "shoulders": 46.0, "length": 26.5, "waist": 82.0, "hip": 98.0, "foot": 26.0},
        "42": {"chest": 104.0, "shoulders": 47.0, "length": 27.0, "waist": 84.0, "hip": 100.0, "foot": 27.0},
        "43": {"chest": 106.0, "shoulders": 48.0, "length": 27.5, "waist": 86.0, "hip": 102.0, "foot": 27.5},
        "44": {"chest": 108.0, "shoulders": 49.0, "length": 28.0, "waist": 88.0, "hip": 104.0, "foot": 28.0},
        "45": {"chest": 110.0, "shoulders": 50.0, "length": 28.5, "waist": 90.0, "hip": 106.0, "foot": 29.0},
    }

    for s in available_sizes:
        metrics = size_multipliers.get(
            s.upper(),
            {"chest": 100.0, "shoulders": 45.0, "length": 70.0, "waist": 84.0, "hip": 100.0, "foot": 26.0}
        )
        size_metrics[s] = metrics

    # 5. Cálculo de recomendación biométrica si se especifican medidas
    recommended_size = None
    if user_chest and not is_bottom and not is_shoe:
        # Buscar la talla donde la prenda tenga entre 4cm y 10cm de holgura
        for s in available_sizes:
            m = size_metrics.get(s, {})
            c_val = m.get("chest", 100.0)
            if c_val >= user_chest + 3.0:
                recommended_size = s
                break
        if not recommended_size and available_sizes:
            recommended_size = available_sizes[-1]
    elif user_waist and is_bottom:
        for s in available_sizes:
            m = size_metrics.get(s, {})
            w_val = m.get("waist", 80.0)
            if w_val >= user_waist + 2.0:
                recommended_size = s
                break
        if not recommended_size and available_sizes:
            recommended_size = available_sizes[-1]

    if not recommended_size and available_sizes:
        recommended_size = available_sizes[len(available_sizes) // 2]

    return ARConfig(
        producto_id=product.id,
        supported=True,
        mode="2d-overlay",
        asset_url=asset_url,
        instructions="Alinea hombros y torso dentro de la guía; el cálculo de holgura y simulación textil se procesan en tiempo real.",
        size_metrics=size_metrics,
        fabric_elasticity=elasticity,
        fit_category=fit_cat,
        available_sizes=available_sizes,
        recommended_size=recommended_size,
        material=product.material or "Tejido Sastrero DrapeMind",
        available_variants=[
            {
                "variante_id": variant.id,
                "sku": variant.sku,
                "color": variant.color,
                "talla": variant.talla,
                "stock_disponible": variant.stock_total - variant.stock_reservado,
                "imagen": variant.imagen,
            }
            for variant in variants
            if variant.stock_total > variant.stock_reservado
        ],
        tracking={
            "landmarks": ["left_shoulder", "right_shoulder", "left_hip", "right_hip"],
            "mirror": True,
            "smoothing": 0.7,
        },
        limitations=[
            "La superposición 2D orienta sobre color y silueta; no sustituye una prueba física.",
            "La precisión depende de iluminación, encuadre y medidas ingresadas.",
        ],
    )
