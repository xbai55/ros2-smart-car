from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator
from uuid import UUID


class SlamMapIn(BaseModel):
    request_id: UUID
    robot_id: str = Field(min_length=1, max_length=36)
    name: str = Field(min_length=1, max_length=128)
    floor: str = Field(default="1F", max_length=64)
    description: str = Field(default="", max_length=2000)

    @field_validator("name")
    @classmethod
    def strip_slam_name(cls, value):
        if not value.strip():
            raise ValueError("地图名称不能为空")
        return value.strip()


class MapIn(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    floor: str = Field(default="1F", max_length=64)
    description: str = ""
    resolution: float = Field(default=0.05, gt=0)
    width: int = Field(default=0, ge=0)
    height: int = Field(default=0, ge=0)
    origin: list[float] = Field(default_factory=list)
    image_key: Optional[str] = None
    file_url: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    active: bool = True


class MapOptimizationIn(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)
    request_id: UUID
    name: str = Field(min_length=1, max_length=128)
    operations: list[dict[str, Any]] = Field(min_length=0, max_length=100)

    @field_validator("name")
    @classmethod
    def strip_name(cls, value):
        if not value.strip():
            raise ValueError("地图名称不能为空")
        return value.strip()


class MapUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    floor: str | None = Field(default=None, max_length=64)
    description: str | None = Field(default=None, max_length=2000)
    active: bool | None = None

    @field_validator("name")
    @classmethod
    def strip_name(cls, value):
        if value is not None and not value.strip():
            raise ValueError("名称不能为空")
        return value.strip() if value is not None else None


class MapPlaceIn(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)
    name: str = Field(min_length=1, max_length=128)
    x: float = Field(ge=0)
    y: float = Field(ge=0)
    yaw: float = 0.0

    @field_validator("name")
    @classmethod
    def strip_name(cls, value):
        if not value.strip():
            raise ValueError("地点名称不能为空")
        return value.strip()


class RouteIn(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    map_id: Optional[str] = None
    status: str = Field(default="active", pattern="^(active|draft|archived)$")
    points: list[dict] = Field(default_factory=list)
    start_point: dict[str, Any] = Field(default_factory=dict)
    end_point: dict[str, Any] = Field(default_factory=dict)
    waypoints: list[dict] = Field(default_factory=list)
    path: list[dict] = Field(default_factory=list)
    parameters: dict[str, Any] = Field(default_factory=dict)


class PatrolCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    robot_id: Optional[str] = None
    route_id: Optional[str] = None
    priority: str = Field(default="normal", pattern="^(low|normal|high|urgent)$")
    inspection_points: list[dict] = Field(default_factory=list)


class PatrolAction(BaseModel):
    action: str = Field(pattern="^(start|pause|resume|cancel|complete|fail)$")


class MissionCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    robot_id: Optional[str] = None
    route_id: Optional[str] = None
    cargo: str = ""
    origin: str = ""
    destination: str = ""
    pickup_code: str = ""
    steps: list[dict] = Field(default_factory=list)


class MissionAction(BaseModel):
    action: str = Field(
        pattern="^(dispatch|pickup|transporting|handover|cancel|complete|fail)$"
    )
    note: str = ""


class IncidentCreate(BaseModel):
    type: str = Field(min_length=1, max_length=48)
    severity: str = Field(default="warning", pattern="^(info|warning|critical)$")
    robot_id: Optional[str] = None
    task_id: Optional[str] = None
    title: str = Field(min_length=1, max_length=255)
    description: str = ""
    location: str = Field(default="", max_length=255)
    media_keys: list[str] = Field(default_factory=list)
    image_url: Optional[str] = None
    video_url: Optional[str] = None
    occurred_at: Optional[str] = None


class IncidentUpdate(BaseModel):
    type: Optional[str] = Field(default=None, max_length=48)
    severity: Optional[str] = Field(default=None, pattern="^(info|warning|critical)$")
    status: Optional[str] = Field(
        default=None,
        pattern="^(open|acknowledged|handling|processing|resolved|dismissed|ignored)$",
    )
    title: Optional[str] = Field(default=None, max_length=255)
    description: Optional[str] = None
    location: Optional[str] = Field(default=None, max_length=255)
    handle_result: Optional[str] = None
    resolution_note: Optional[str] = None
    image_url: Optional[str] = None
    video_url: Optional[str] = None


class IncidentAction(BaseModel):
    action: str = Field(pattern="^(confirm|handle|resolve|dismiss|ignore)$")
    note: str = ""


class NotificationRead(BaseModel):
    read: bool = True


class SettingUpdate(BaseModel):
    values: dict[str, str]
