from datetime import date, datetime, timezone, timedelta
from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException, Response, Query, UploadFile, File
from sqlalchemy import select, func, cast, Date
from sqlalchemy.orm import Session
from app.api.deps import require_roles, get_current_user
from app.db.session import get_db
from app.models import User, Role, Order, Product
from app.services.saas import require_active_subscription
from app.incrementos.incremento_iii.models import BusinessReport
from app.incrementos.incremento_iii.router import facts, ReportInput
from .spreadsheet import workbook
from .forecast import forecast

router = APIRouter(tags=['Incremento IV · CU-26 a CU-30'])
admin = require_roles(Role.ADMIN)


@router.post('/ar/products/{product_id}/body-asset')
async def upload_body_asset(product_id: int, file: UploadFile = File(...), user: User = Depends(admin), db: Session = Depends(get_db)):
    from io import BytesIO
    from uuid import uuid4
    from PIL import Image, UnidentifiedImageError
    from app.modules.catalogo_y_comercializacion.cu29_gestionar_productos_de_ropa import STATIC_PRODUCTS_DIR
    require_active_subscription(db, user.tenant_id)
    product = db.scalar(select(Product).where(Product.id == product_id).with_for_update())
    if not product or not product.activo:
        raise HTTPException(404, 'Prenda no encontrada')
    contents = await file.read(8 * 1024 * 1024 + 1)
    if len(contents) > 8 * 1024 * 1024:
        raise HTTPException(413, 'La imagen debe pesar hasta 8 MB')
    try:
        image = Image.open(BytesIO(contents))
        if image.format not in ('PNG', 'WEBP') or image.width < 64 or image.height < 64 or image.width * image.height > 16000000:
            raise ValueError('Image size or format')
        rgba = image.convert('RGBA')
        minimum, maximum = rgba.getchannel('A').getextrema()
        if minimum == 255 or maximum == 0:
            raise ValueError('Transparent background required')
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as exc:
        raise HTTPException(422, 'Sube una imagen PNG o WebP de al menos 64 × 64, con la prenda visible y el fondo transparente.') from exc
    folder = STATIC_PRODUCTS_DIR / str(user.tenant_id)
    folder.mkdir(parents=True, exist_ok=True)
    filename = f'{uuid4().hex}-body.png'
    target = folder / filename
    asset = {'ar_asset': f'/static/products/{user.tenant_id}/{filename}', 'ar_category': 'upper_body'}
    try:
        rgba.save(target, format='PNG')
        product.imagenes = [item for item in (product.imagenes or []) if not (isinstance(item, dict) and item.get('ar_asset'))] + [asset]
        db.commit()
    except Exception:
        db.rollback()
        target.unlink(missing_ok=True)
        raise
    return asset


@router.get('/ar/products/{product_id}/body-asset')
def body_asset(product_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from urllib.parse import urlparse
    require_active_subscription(db, user.tenant_id)
    product = db.get(Product, product_id)
    if not product or not product.activo:
        raise HTTPException(404, 'Prenda no encontrada')
    # Only an explicitly prepared catalog asset is suitable. A normal photograph
    # or the demonstration shirt must never replace the customer's selection.
    for image in product.imagenes or []:
        if not isinstance(image, dict) or not image.get('ar_asset'):
            continue
        if image.get('ar_category') != 'upper_body':
            continue
        asset = str(image['ar_asset'])
        url = urlparse(asset)
        if (url.scheme == 'https' and url.netloc and not url.username and not url.password) or (asset.startswith('/static/') and not asset.startswith('//') and '..' not in asset):
            return {'producto_id': product.id, 'nombre': product.nombre, 'asset_url': asset,
                    'modo': 'upper-body-2d', 'privacidad': 'La cámara se procesa en el dispositivo; no se envían fotogramas.'}
    raise HTTPException(409, 'Esta prenda todavía no tiene una imagen transparente preparada para el vestidor corporal. Puedes consultar sus tallas y medidas.')


@router.get('/business-reports/{report_id}/xlsx')
def export_report(report_id: int, user: User = Depends(admin), db: Session = Depends(get_db)):
    require_active_subscription(db, user.tenant_id, 'ai_reports')
    row = db.get(BusinessReport, report_id)
    if not row:
        raise HTTPException(404, 'Reporte no encontrado')
    report = row.resultado
    data = report['datos']
    rows = [['Reporte empresarial', report['titulo']], ['Empresa', data['empresa']], ['Sucursal', data['sucursal']],
            ['Desde', data['desde']], ['Hasta', data['hasta']], ['Consulta', row.consulta],
            ['Pedidos pagados', data['pedidos_pagados']], ['Ingreso neto cobrado (BOB)', float(Decimal(data['ingreso_neto_cobrado']))],
            ['Unidades disponibles ahora', data['inventario_actual']['unidades_disponibles']],
            ['Alcance', data['alcance']], ['Análisis NVIDIA', report['analisis']], ['Prenda', 'Unidades']]
    rows.extend([item['nombre'], item['cantidad']] for item in data['prendas_vendidas'])
    rows.extend(['Recomendación', action] for action in report['recomendaciones'])
    return Response(workbook(rows), media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                    headers={'Content-Disposition': f'attachment; filename="reporte-{row.id}.xlsx"', 'Cache-Control': 'private, no-store', 'X-Content-Type-Options': 'nosniff'})


@router.get('/business-dashboard')
def dashboard(days: int = Query(30, ge=1, le=366), sucursal_id: int | None = Query(None, gt=0),
              user: User = Depends(admin), db: Session = Depends(get_db)):
    require_active_subscription(db, user.tenant_id)
    today = datetime.now(timezone.utc).date()
    return facts(db, ReportInput(consulta='Indicadores comerciales', desde=today-timedelta(days=days-1), hasta=today, sucursal_id=sucursal_id), user)


@router.get('/business-predictions')
def predictions(sucursal_id: int | None = Query(None, gt=0), user: User = Depends(admin), db: Session = Depends(get_db)):
    require_active_subscription(db, user.tenant_id)
    # Validate branch ownership using the same server-side scope as dashboard.
    scope = facts(db, ReportInput(consulta='Predicción de pedidos', sucursal_id=sucursal_id), user)
    today = datetime.now(timezone.utc).date()
    filters = [Order.paid_at.is_not(None), Order.estado != 'CANCELADO', Order.paid_at < datetime.combine(today, datetime.min.time(), tzinfo=timezone.utc)]
    if sucursal_id:
        filters.append(Order.sucursal_id == sucursal_id)
    first = db.scalar(select(func.min(Order.paid_at)).where(*filters))
    if first is None:
        return {**forecast([], today), 'empresa': scope['empresa'], 'sucursal': scope['sucursal']}
    first_utc = first.replace(tzinfo=timezone.utc) if first.tzinfo is None else first.astimezone(timezone.utc)
    start = max(first_utc.date(), today-timedelta(days=180))
    filters.append(Order.paid_at >= datetime.combine(start, datetime.min.time(), tzinfo=timezone.utc))
    day = cast(func.timezone('UTC', Order.paid_at), Date) if db.bind.dialect.name == 'postgresql' else func.date(Order.paid_at)
    rows = db.execute(select(day, func.count(Order.id)).where(*filters).group_by(day)).all()
    counts = {value if isinstance(value, date) else date.fromisoformat(value): count for value, count in rows}
    series = [counts.get(start+timedelta(days=i), 0) for i in range((today-start).days)]
    return {**forecast(series, start), 'empresa': scope['empresa'], 'sucursal': scope['sucursal'], 'corte': str(today), 'zona_horaria': 'UTC'}
