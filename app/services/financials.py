"""Ingresos netos: un crédito por cambio no representa efectivo ingresado otra vez."""
from decimal import Decimal
from sqlalchemy import select,func,case,and_
from app.models import Payment,Order
from app.incrementos.incremento_ii.models import GarmentExchange


def net_payments(db,*filters):
    amount=case(
        (and_(Payment.estado=='APROBADO',Payment.metodo!='CREDITO_CAMBIO'),Payment.monto),
        (and_(Payment.estado=='REEMBOLSADO',Payment.proveedor=='CAMBIO_DEVOLUCION'),-Payment.monto),
        else_=0)
    return db.scalar(select(func.coalesce(func.sum(amount),0)).where(*filters)) or Decimal('0')


def net_delivered_orders(db):
    gross=db.scalar(select(func.coalesce(func.sum(Order.total),0)).where(Order.estado=='ENTREGADO')) or Decimal('0')
    credits=db.scalar(select(func.coalesce(func.sum(GarmentExchange.credito),0))) or Decimal('0')
    return gross-credits
