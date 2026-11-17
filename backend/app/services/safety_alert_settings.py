"""Persist independent detector and DS review score gates."""
import json
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from ..models import AppSetting

class CategoryThresholds(BaseModel):
    model_config = ConfigDict(extra='forbid')
    candidate: float = Field(default=.5, ge=0, le=1, strict=True, allow_inf_nan=False)
    review: float = Field(default=.8, ge=0, le=1, strict=True, allow_inf_nan=False)

class AlertThresholds(BaseModel):
    model_config = ConfigDict(extra='forbid')
    smoke_fire: CategoryThresholds = Field(default_factory=CategoryThresholds)
    fallen_person: CategoryThresholds = Field(default_factory=CategoryThresholds)

KEY='safety_alert_thresholds'
def read_thresholds(db):
    row=db.scalar(select(AppSetting).where(AppSetting.key==KEY))
    return AlertThresholds.model_validate_json(row.value) if row else AlertThresholds()

def save_thresholds(db, value):
    row=db.scalar(select(AppSetting).where(AppSetting.key==KEY))
    if row is None:
        from uuid import uuid4
        row=AppSetting(id=str(uuid4()),key=KEY);db.add(row)
    row.value=value.model_dump_json()
    db.flush()
    return value.model_dump()
