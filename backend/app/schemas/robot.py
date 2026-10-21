from typing import Any, Optional

from pydantic import BaseModel, Field

STATUS_PATTERN = "^(online|degraded|offline|estop|charging)$"
HEALTH_PATTERN = "^(good|warning|critical)$"
MODE_PATTERN = "^(stop|manual|patrol|transport|mapping|follow|object_follow|charging)$"


class RobotCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    robot_code: str = Field(default="", max_length=64)
    serial: Optional[str] = Field(default=None, max_length=128)
    model: str = Field(default="ROSMASTER X3", max_length=64)
    status: str = Field(default="offline", pattern=STATUS_PATTERN)
    mode: str = Field(default="stop", max_length=32)
    health: str = Field(default="good", pattern=HEALTH_PATTERN)
    battery: float = Field(default=100.0, ge=0, le=100)
    speed: float = 0.0
    position: dict[str, Any] = Field(default_factory=dict)
    network: dict[str, Any] = Field(default_factory=dict)
    temperature: Optional[float] = None
    current_map: Optional[str] = None
    current_task: Optional[str] = None


class RobotUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=128)
    robot_code: Optional[str] = Field(default=None, max_length=64)
    model: Optional[str] = Field(default=None, max_length=64)
    status: Optional[str] = Field(default=None, pattern=STATUS_PATTERN)
    mode: Optional[str] = Field(default=None, max_length=32)
    health: Optional[str] = Field(default=None, pattern=HEALTH_PATTERN)
    battery: Optional[float] = Field(default=None, ge=0, le=100)
    speed: Optional[float] = None
    position: Optional[dict[str, Any]] = None
    network: Optional[dict[str, Any]] = None
    temperature: Optional[float] = None
    current_map: Optional[str] = None
    current_task: Optional[str] = None


class RobotControlIn(BaseModel):
    """前端控制意图，例如 {"command": "forward", "speed": 0.3}。"""

    command: str = Field(min_length=1, max_length=32)
    speed: Optional[float] = Field(default=None, ge=-1.5, le=1.5)
    params: dict[str, Any] = Field(default_factory=dict)


class EmergencyStopIn(BaseModel):
    enabled: bool = True
    reason: str = Field(default="", max_length=255)
