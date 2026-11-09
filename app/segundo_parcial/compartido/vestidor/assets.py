from fastapi import APIRouter
from app.segundo_parcial.compartido.indicadores import (
    Depends,
    File,
    HTTPException,
    Product,
    Session,
    UploadFile,
    User,
    admin,
    get_current_user,
    get_db,
    require_active_subscription,
    select,
)

router = APIRouter(prefix="", tags=["Vestidor compartido"])


@router.post("/ar/products/{product_id}/body-asset")
async def upload_body_asset(
    product_id: int,
    file: UploadFile = File(...),
    user: User = Depends(admin),
    db: Session = Depends(get_db),
):
    from io import BytesIO
    from uuid import uuid4
    from PIL import Image, UnidentifiedImageError
    from app.segundo_parcial.cu08_productos.cu08_productos import STATIC_PRODUCTS_DIR

    require_active_subscription(db, user.tenant_id)
    product = db.scalar(
        select(Product).where(Product.id == product_id).with_for_update()
    )
    if not product or not product.activo:
        raise HTTPException(404, "Prenda no encontrada")
    contents = await file.read(8 * 1024 * 1024 + 1)
    if len(contents) > 8 * 1024 * 1024:
        raise HTTPException(413, "La imagen debe pesar hasta 8 MB")
    try:
        image = Image.open(BytesIO(contents))
        if (
            image.format not in ("PNG", "WEBP")
            or image.width < 64
            or image.height < 64
            or image.width * image.height > 16000000
        ):
            raise ValueError("Image size or format")
        rgba = image.convert("RGBA")
        minimum, maximum = rgba.getchannel("A").getextrema()
        if minimum == 255 or maximum == 0:
            raise ValueError("Transparent background required")
    except (
        UnidentifiedImageError,
        OSError,
        ValueError,
        Image.DecompressionBombError,
    ) as exc:
        raise HTTPException(
            422,
            "Sube una imagen PNG o WebP de al menos 64 × 64, con la prenda visible y el fondo transparente.",
        ) from exc
    folder = STATIC_PRODUCTS_DIR / str(user.tenant_id)
    folder.mkdir(parents=True, exist_ok=True)
    filename = f"{uuid4().hex}-body.png"
    target = folder / filename
    asset = {
        "ar_asset": f"/static/products/{user.tenant_id}/{filename}",
        "ar_category": "upper_body",
    }
    try:
        rgba.save(target, format="PNG")
        product.imagenes = [
            item
            for item in (product.imagenes or [])
            if not (isinstance(item, dict) and item.get("ar_asset"))
        ] + [asset]
        db.commit()
    except Exception:
        db.rollback()
        target.unlink(missing_ok=True)
        raise
    return asset


@router.get("/ar/products/{product_id}/body-asset")
def body_asset(
    product_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from urllib.parse import urlparse

    require_active_subscription(db, user.tenant_id)
    product = db.get(Product, product_id)
    if not product or not product.activo:
        raise HTTPException(404, "Prenda no encontrada")
    # Only an explicitly prepared catalog asset is suitable. A normal photograph
    # or the demonstration shirt must never replace the customer's selection.
    for image in product.imagenes or []:
        if not isinstance(image, dict) or not image.get("ar_asset"):
            continue
        if image.get("ar_category") != "upper_body":
            continue
        asset = str(image["ar_asset"])
        url = urlparse(asset)
        if (
            url.scheme == "https"
            and url.netloc
            and not url.username
            and not url.password
        ) or (
            asset.startswith("/static/")
            and not asset.startswith("//")
            and ".." not in asset
        ):
            return {
                "producto_id": product.id,
                "nombre": product.nombre,
                "asset_url": asset,
                "modo": "upper-body-2d",
                "privacidad": "La cámara se procesa en el dispositivo; no se envían fotogramas.",
            }
    raise HTTPException(
        409,
        "Esta prenda todavía no tiene una imagen transparente preparada para el vestidor corporal. Puedes consultar sus tallas y medidas.",
    )
