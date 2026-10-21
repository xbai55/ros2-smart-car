from typing import Any, Optional

from pydantic import BaseModel, Field

PRIORITY_PATTERN = "^(low|normal|high|urgent)$"
PATROL_STATUS_PATTERN = "^(pending|running|paused|completed|failed|cancelled)$"
MISSION_STATUS_PATTERN = "^(queued|dispatched|transporting|completed|failed|cancelled)$"


class PatrolTaskCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    description: str = ""
    robot_id: Optional[str] = None
    map_id: Optional[str] = None
    route_id: Optional[str] = None
    target_area: str = Field(default="", max_length=128)
    priority: str = Field(default="normal", pattern=PRIORITY_PATTERN)
    inspection_points: list[dict[str, Any]] = Field(default_factory=list)
    status: Optional[str] = Field(default=None, pattern=PATROL_STATUS_PATTERN)


class PatrolTaskUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=128)
    description: Optional[str] = None
    robot_id: Optional[str] = None
    map_id: Optional[str] = None
    route_id: Optional[str] = None
    target_area: Optional[str] = Field(default=None, max_length=128)
    priority: Optional[str] = Field(default=None, pattern=PRIORITY_PATTERN)
    status: Optional[str] = Field(default=None, pattern=PATROL_STATUS_PATTERN)
    progress: Optional[float] = Field(default=None, ge=0, le=100)
    inspection_points: Optional[list[dict[str, Any]]] = None


class MissionTaskCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    description: str = ""
    cargo_name: str = ""
    cargo: str = ""
    start_location: str = ""
    origin: str = ""
    end_location: str = ""
    destination: str = ""
    robot_id: Optional[str] = None
    map_id: Optional[str] = None
    route_id: Optional[str] = None
    pickup_code: str = Field(default="", max_length=32)
    steps: list[dict[str, Any]] = Field(default_factory=list)
    status: Optional[str] = Field(default=None, pattern=MISSION_STATUS_PATTERN)


class MissionTaskUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=128)
    description: Optional[str] = None
    cargo_name: Optional[str] = None
    start_location: Optional[str] = None
    end_location: Optional[str] = None
    robot_id: Optional[str] = None
    map_id: Optional[str] = None
    route_id: Optional[str] = None
    pickup_code: Optional[str] = Field(default=None, max_length=32)
    steps: Optional[list[dict[str, Any]]] = None
    status: Optional[str] = Field(default=None, pattern=MISSION_STATUS_PATTERN)
    progress: Optional[float] = Field(default=None, ge=0, le=100)
