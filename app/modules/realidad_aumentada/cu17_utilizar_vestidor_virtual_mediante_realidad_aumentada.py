from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user_optional
from app.core.config import settings
from app.db.session import get_db
from app.models import Product, ProductVariant, User
from app.schemas.api import ARConfig

router = APIRouter()


@router.get("/capabilities", summary="CU-17: Capacidades del probador virtual")
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
    summary="CU-17: Configuración de probador AR",
    description=(
        "CU-17. La cámara, segmentación y render se ejecutan en Flutter. El backend valida el producto, "
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

    asset_url = None
    for image in product.imagenes or []:
        if isinstance(image, dict) and image.get("ar_asset"):
            asset_url = image["ar_asset"]
            break
        elif isinstance(image, str) and (
            image.endswith(".png") or image.endswith(".webp")
        ):
            asset_url = image

    if not asset_url and product.tags_ai and "ar-ready" in product.tags_ai:
        asset_url = f"{settings.AR_ASSET_BASE_URL.rstrip('/')}/{product.id}.png"

    if not asset_url and product.imagenes and len(product.imagenes) > 0:
        first_img = product.imagenes[0]
        asset_url = (
            first_img.get("url") if isinstance(first_img, dict) else str(first_img)
        )

    variants = list(
        db.scalars(
            select(ProductVariant)
            .where(
                ProductVariant.producto_id == product.id,
                ProductVariant.activo.is_(True),
            )
            .order_by(ProductVariant.color, ProductVariant.talla)
        )
    )
    available_sizes: list[str] = []
    for v in variants:
        if v.activo and v.talla and v.talla not in available_sizes:
            available_sizes.append(v.talla)

    if not available_sizes:
        available_sizes = ["S", "M", "L", "XL"]

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

    elasticity = 0.05
    if "lino" in material_l or "seda" in material_l:
        elasticity = 0.02
    elif "cuero" in material_l or "denim" in material_l:
        elasticity = 0.01
    elif "algodon" in material_l or "algodón" in material_l:
        elasticity = 0.07
    elif (
        "punto" in material_l
        or "spandex" in material_l
        or "elastano" in material_l
    ):
        elasticity = 0.18

    size_matrix = {
        "XS": {"chest_cm": 88, "waist_cm": 74, "length_cm": 68, "scale": 0.92},
        "S": {"chest_cm": 94, "waist_cm": 80, "length_cm": 70, "scale": 0.96},
        "M": {"chest_cm": 100, "waist_cm": 86, "length_cm": 72, "scale": 1.00},
        "L": {"chest_cm": 106, "waist_cm": 92, "length_cm": 74, "scale": 1.04},
        "XL": {"chest_cm": 112, "waist_cm": 98, "length_cm": 76, "scale": 1.08},
        "XXL": {"chest_cm": 118, "waist_cm": 104, "length_cm": 78, "scale": 1.12},
    }

    recommended_size = "M"
    if user_chest:
        for sz, dims in size_matrix.items():
            if dims["chest_cm"] >= user_chest:
                recommended_size = sz
                break

    return ARConfig(
        product_id=product.id,
        nombre=product.nombre,
        categoria_id=product.categoria_id,
        asset_2d_url=asset_url or "/static/ar/default_garment.png",
        mesh_type="upper_body",
        anchors=["left_shoulder", "right_shoulder", "left_hip", "right_hip"],
        available_sizes=available_sizes,
        size_matrix=size_matrix,
        recommended_size=recommended_size,
        fit_category=fit_cat,
        fabric_physics={
            "stiffness": 0.65,
            "damping": 0.8,
            "elasticity": elasticity,
            "weight_gsm": 180,
        },
    )

