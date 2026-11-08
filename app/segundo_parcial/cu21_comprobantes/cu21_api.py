from fastapi import APIRouter
from app.segundo_parcial.compartido.reportes import (
    Depends,
    HTTPException,
    Session,
    User,
    document,
    download_receipt,
    get_current_user,
    get_db,
    get_order,
    pdf_response,
)

router = APIRouter(prefix="", tags=["CU-21 · comprobantes"])


@router.get("/orders/{order_id}/receipt.pdf")
def receipt_pdf(
    order_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    order = get_order(order_id, user, db)
    if not order.paid_at:
        raise HTTPException(
            409, "El comprobante de venta estará disponible cuando se confirme el pago"
        )
    data = download_receipt(order_id, "json", user, db)
    lines = [
        f"Empresa: {data['empresa']['nombre']}",
        f"Sucursal: {data['sucursal']['nombre']}",
        f"Dirección: {data['sucursal']['direccion']}",
        f"Contacto: {data['empresa']['telefono']}",
        f"Pedido: {order.codigo_publico}",
        f"Fecha: {order.created_at:%d/%m/%Y %H:%M} UTC",
        f"Estado: {order.estado}",
        f"Cliente: {data['cliente']['nombre']}",
        "",
        "Prendas:",
    ]
    for item in data["items"]:
        lines.extend(
            [
                f"{item['cantidad']} x {item['nombre']} | Talla {item['talla']} | {item['color']}",
                f"SKU {item['sku']} | Bs {item['precio_unitario']:.2f} | Subtotal Bs {item['subtotal']:.2f}",
            ]
        )
    lines.extend(
        [
            "",
            f"Subtotal: Bs {order.subtotal:.2f}",
            f"Descuento: Bs {order.descuento:.2f}",
            f"Envío: Bs {order.costo_envio:.2f}",
            f"Total: Bs {order.total:.2f}",
            "",
            "Documento no fiscal. Consulta las condiciones de cambios de esta tienda.",
        ]
    )
    return pdf_response(
        document("Comprobante de venta", lines), f"comprobante-{order.id}.pdf"
    )
