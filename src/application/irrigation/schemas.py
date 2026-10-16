from datetime import date
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel

IrrigationStatus = Literal["regar", "cubierto", "no_regar_lluvia"]


class CycleIrrigation(BaseModel):
    crop_cycle_id: UUID
    crop_name: str
    kc: float
    etc_mm: float
    recent_irrigation_mm: float
    net_mm: float
    status: IrrigationStatus
    message: str
    suggested_mm: Optional[float] = None  # to apply on `next_irrigation_date`
    next_irrigation_date: Optional[date] = None  # null: no need within the forecast horizon


class FieldIrrigationResult(BaseModel):
    field_id: UUID
    field_name: str
    et0_mm: float
    rain_forecast_mm: float
    field_kc: Optional[float] = None
    field_etc_mm: Optional[float] = None
    field_recent_irrigation_mm: Optional[float] = None
    field_net_mm: Optional[float] = None
    field_status: Optional[IrrigationStatus] = None
    field_message: Optional[str] = None
    suggested_mm: Optional[float] = None
    next_irrigation_date: Optional[date] = None
    cycles: list[CycleIrrigation] = []
