"""Discounts over persisted basket lines, restricted to the promotion's product."""
from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime, timezone


def promotion_issue(promotion, lines, now=None):
    now=now or datetime.now(timezone.utc)
    def aware(value): return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value
    if not promotion.activo: return 'La promoción ya no está activa.'
    if promotion.fecha_inicio and aware(promotion.fecha_inicio)>now: return 'La promoción todavía no comenzó.'
    if promotion.fecha_fin and aware(promotion.fecha_fin)<now: return 'La promoción ha vencido.'
    if promotion.limite_usos and promotion.usos_actuales>=promotion.limite_usos: return 'La promoción agotó sus usos disponibles.'
    eligible=[row for row in lines if not promotion.producto_id or row[0]==promotion.producto_id]
    if not eligible: return 'La promoción no corresponde a las prendas de tu carrito.'
    quantity=sum(row[1] for row in eligible)
    if quantity < (promotion.cantidad_minima or 1): return f'La oferta requiere {promotion.cantidad_minima} prendas participantes; faltan {promotion.cantidad_minima - quantity}.'
    if sum((Decimal(str(price))*qty for _,qty,price in lines),Decimal('0')) < promotion.monto_minimo_compra:
        return f'Requiere una compra mínima de Bs {promotion.monto_minimo_compra:.2f}.'
    return None


def basket_discount(promotion, lines):
    """lines: (product_id, quantity, server-side unit price); 2x1 pairs same product."""
    eligible=[(pid,int(qty),Decimal(str(price))) for pid,qty,price in lines if not promotion.producto_id or pid==promotion.producto_id]
    if sum(qty for _,qty,_ in eligible) < (getattr(promotion,'cantidad_minima',1) or 1):
        return Decimal('0.00')
    subtotal=sum((price*qty for _,qty,price in eligible),Decimal('0'))
    if promotion.tipo_descuento in ('PORCENTAJE','POR_CANTIDAD'):
        amount=subtotal*min(promotion.valor_descuento,Decimal('100'))/Decimal('100')
    elif promotion.tipo_descuento=='DOS_POR_UNO':
        grouped=defaultdict(list)
        for pid,qty,price in eligible:grouped[pid].append((price,qty))
        amount=Decimal('0')
        for offers in grouped.values():
            free=sum(qty for _,qty in offers)//2
            for price,qty in sorted(offers):
                used=min(qty,free);amount+=price*used;free-=used
                if not free:break
    else:
        amount=promotion.valor_descuento
    return max(Decimal('0'),min(subtotal,amount)).quantize(Decimal('0.01'),rounding=ROUND_HALF_UP)
