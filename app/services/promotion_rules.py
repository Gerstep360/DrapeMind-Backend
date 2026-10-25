"""Discounts over persisted basket lines, restricted to the promotion's product."""
from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP


def basket_discount(promotion, lines):
    """lines: (product_id, quantity, server-side unit price); 2x1 pairs same product."""
    eligible=[(pid,int(qty),Decimal(str(price))) for pid,qty,price in lines if not promotion.producto_id or pid==promotion.producto_id]
    subtotal=sum((price*qty for _,qty,price in eligible),Decimal('0'))
    if promotion.tipo_descuento=='PORCENTAJE':
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
