from datetime import datetime
from uuid import UUID
from decimal import Decimal
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator
from app.schemas.api import SupplierInput, SupplierProductInput


class Input(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)


class SupplierWrite(SupplierInput):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)


class OfferWrite(SupplierProductInput):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    costo_unitario: Decimal = Field(gt=0, max_digits=10, decimal_places=2)


class SupplierAccount(Input):
    nombre: str = Field(min_length=2, max_length=120)
    email: str = Field(min_length=5, max_length=150, pattern=r'^[^\s@]+@[^\s@]+\.[^\s@]+$')
    password: str = Field(min_length=8, max_length=72)


class SupplyLine(Input):
    suministro_id: int = Field(gt=0)
    variante_id: int | None = Field(default=None, gt=0)
    cantidad: int = Field(gt=0, le=100000)


class SupplyCreate(Input):
    request_id: UUID
    proveedor_id: int = Field(gt=0)
    sucursal_id: int = Field(gt=0)
    observacion: str | None = Field(default=None, max_length=300)
    items: list[SupplyLine] = Field(min_length=1, max_length=100)

    @model_validator(mode='after')
    def unique_items(self):
        if len({i.suministro_id for i in self.items}) != len(self.items):
            raise ValueError('Agrupa las cantidades de un mismo suministro en una sola línea')
        return self


class ReservationLine(Input):
    variante_id: int = Field(gt=0)
    cantidad: int = Field(gt=0, le=100)


class OfflineReservation(Input):
    operacion_id: UUID
    sucursal_id: int = Field(gt=0)
    snapshot_version: str = Field(min_length=1, max_length=64)
    creado_at: datetime
    observacion: str | None = Field(default=None, max_length=300)
    items: list[ReservationLine] = Field(min_length=1, max_length=50)

    @model_validator(mode='after')
    def valid_items(self):
        if len({i.variante_id for i in self.items}) != len(self.items):
            raise ValueError('Agrupa las cantidades de una misma variante')
        if self.creado_at.tzinfo is None:
            raise ValueError('La fecha debe incluir la zona horaria')
        return self


class CashLine(ReservationLine):
    precio_unitario: Decimal = Field(ge=0, max_digits=10, decimal_places=2)


class CashSale(OfflineReservation):
    items: list[CashLine] = Field(min_length=1, max_length=50)
    cliente_id: int | None = Field(default=None, gt=0)
    efectivo_recibido: Decimal = Field(ge=0, max_digits=12, decimal_places=2)


class ReservationPickup(CashSale):
    reserva_id: int = Field(gt=0)


class SyncEnvelope(Input):
    tipo: Literal['RESERVATION','SALE','PICKUP']
    payload: dict

    @model_validator(mode='after')
    def validate_payload(self):
        model = {'RESERVATION':OfflineReservation,'SALE':CashSale,'PICKUP':ReservationPickup}[self.tipo]
        self.payload = model.model_validate(self.payload).model_dump(mode='json')
        return self


class ConflictResolution(Input):
    accion: Literal['RETRY','REJECT']
    motivo: str = Field(min_length=5,max_length=300)
    aceptar_precio_guardado: bool = False
    efectivo_devuelto: bool = False


class OperationLookup(Input):
    operaciones: list[UUID] = Field(min_length=1,max_length=100)


class ReservationPreparation(Input):
    estado: Literal['CONFIRMADA','EN_PREPARACION','LISTA']


class ReturnedLine(Input):
    item_pedido_id: int = Field(gt=0)
    cantidad: int = Field(gt=0,le=100)


class ExchangeCreate(Input):
    operacion_id: UUID
    pedido_origen_id: int = Field(gt=0)
    sucursal_id: int = Field(gt=0)
    motivo: str = Field(min_length=5,max_length=300)
    devoluciones: list[ReturnedLine] = Field(min_length=1,max_length=50)
    prendas_nuevas: list[ReservationLine] = Field(min_length=1,max_length=50)
    efectivo_recibido: Decimal = Field(ge=0, max_digits=12, decimal_places=2)
    efectivo_devuelto: Decimal = Field(ge=0, max_digits=12, decimal_places=2)

    @model_validator(mode='after')
    def unique_lines(self):
        if len({i.item_pedido_id for i in self.devoluciones}) != len(self.devoluciones):
            raise ValueError('Agrupa cada prenda devuelta en una línea')
        if len({i.variante_id for i in self.prendas_nuevas}) != len(self.prendas_nuevas):
            raise ValueError('Agrupa cada variante nueva en una línea')
        return self
