from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ..db.base import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Robot(Base):
    __tablename__ = "robots"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), index=True)
    serial: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    robot_code: Mapped[str] = mapped_column(String(64), default="", index=True)
    model: Mapped[str] = mapped_column(String(64), default="ROSMASTER X3")
    status: Mapped[str] = mapped_column(String(16), default="offline")  # online|degraded|offline|estop|charging
    mode: Mapped[str] = mapped_column(String(32), default="stop")
    health: Mapped[str] = mapped_column(String(16), default="good")  # good|warning|critical
    battery: Mapped[float] = mapped_column(Float, default=100.0)
    speed: Mapped[float] = mapped_column(Float, default=0.0)
    position: Mapped[str] = mapped_column(Text, default="{}")
    network: Mapped[str] = mapped_column(Text, default="{}")
    temperature: Mapped[float | None] = mapped_column(Float, nullable=True)
    current_task: Mapped[str | None] = mapped_column(String(36), nullable=True)
    current_map: Mapped[str | None] = mapped_column(String(36), nullable=True)
    last_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_heartbeat: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, onupdate=_utcnow
    )


class Incident(Base):
    __tablename__ = "incidents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    type: Mapped[str] = mapped_column(String(48), index=True)  # smoke_fire|fallen_person|blocked_passage
    severity: Mapped[str] = mapped_column(String(16), default="warning")  # info|warning|critical
    status: Mapped[str] = mapped_column(String(24), default="open", index=True)
    robot_id: Mapped[str | None] = mapped_column(ForeignKey("robots.id"), nullable=True)
    task_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text, default="")
    location: Mapped[str] = mapped_column(String(255), default="")
    media_keys: Mapped[str] = mapped_column(Text, default="[]")
    evidence: Mapped[str] = mapped_column(Text, default="{}")
    image_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    video_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    occurred_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    handled_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    handled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    handle_result: Mapped[str] = mapped_column(Text, default="")
    resolution_note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    kind: Mapped[str] = mapped_column(String(48), default="general")
    title: Mapped[str] = mapped_column(String(255))
    body: Mapped[str] = mapped_column(Text, default="")
    ref_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    read: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    action: Mapped[str] = mapped_column(String(96), index=True)
    resource: Mapped[str] = mapped_column(String(96))
    resource_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    before: Mapped[str] = mapped_column(Text, default="{}")
    after: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class MapModel(Base):
    __tablename__ = "maps"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), index=True)
    floor: Mapped[str] = mapped_column(String(64), default="1F")
    description: Mapped[str] = mapped_column(Text, default="")
    resolution: Mapped[float] = mapped_column(Float, default=0.05)
    width: Mapped[int] = mapped_column(Integer, default=0)
    height: Mapped[int] = mapped_column(Integer, default=0)
    origin: Mapped[str] = mapped_column(Text, default="[]")
    image_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    file_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    # 属性名不能叫 metadata（与 Declarative Base.metadata 冲突），列名仍为 metadata。
    meta: Mapped[str] = mapped_column("metadata", Text, default="{}")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, onupdate=_utcnow
    )


class MapPlace(Base):
    __tablename__ = "map_places"
    __table_args__ = (UniqueConstraint("map_id", "name", name="uq_map_place_name"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    map_id: Mapped[str] = mapped_column(ForeignKey("maps.id"), index=True)
    name: Mapped[str] = mapped_column(String(128))
    # Original image pixels: top-left origin, x rightwards, y downwards.
    x: Mapped[float] = mapped_column(Float)
    y: Mapped[float] = mapped_column(Float)
    yaw: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, onupdate=_utcnow)


class Route(Base):
    __tablename__ = "routes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), index=True)
    map_id: Mapped[str | None] = mapped_column(ForeignKey("maps.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(24), default="active")  # active|draft|archived
    points: Mapped[str] = mapped_column(Text, default="[]")
    start_point: Mapped[str] = mapped_column(Text, default="{}")
    end_point: Mapped[str] = mapped_column(Text, default="{}")
    waypoints: Mapped[str] = mapped_column(Text, default="[]")
    path: Mapped[str] = mapped_column(Text, default="[]")
    parameters: Mapped[str] = mapped_column(Text, default="{}")
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, onupdate=_utcnow
    )


class PatrolTask(Base):
    __tablename__ = "patrol_tasks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    robot_id: Mapped[str | None] = mapped_column(ForeignKey("robots.id"), nullable=True)
    map_id: Mapped[str | None] = mapped_column(ForeignKey("maps.id"), nullable=True)
    route_id: Mapped[str | None] = mapped_column(ForeignKey("routes.id"), nullable=True)
    target_area: Mapped[str] = mapped_column(String(128), default="")
    status: Mapped[str] = mapped_column(String(24), default="pending", index=True)
    priority: Mapped[str] = mapped_column(String(16), default="normal")
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    inspection_points: Mapped[str] = mapped_column(Text, default="[]")
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, onupdate=_utcnow
    )


class MissionTask(Base):
    __tablename__ = "mission_tasks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    robot_id: Mapped[str | None] = mapped_column(ForeignKey("robots.id"), nullable=True)
    map_id: Mapped[str | None] = mapped_column(ForeignKey("maps.id"), nullable=True)
    route_id: Mapped[str | None] = mapped_column(ForeignKey("routes.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(24), default="queued", index=True)
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    cargo: Mapped[str] = mapped_column(String(255), default="")
    cargo_name: Mapped[str] = mapped_column(String(255), default="")
    origin: Mapped[str] = mapped_column(String(255), default="")
    destination: Mapped[str] = mapped_column(String(255), default="")
    start_location: Mapped[str] = mapped_column(String(255), default="")
    end_location: Mapped[str] = mapped_column(String(255), default="")
    pickup_code: Mapped[str] = mapped_column(String(32), default="")
    steps: Mapped[str] = mapped_column(Text, default="[]")
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    pickup_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    handover_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, onupdate=_utcnow
    )


class AppSetting(Base):
    __tablename__ = "app_settings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    key: Mapped[str] = mapped_column(String(96), unique=True, index=True)
    value: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utcnow,
        onupdate=_utcnow,
    )
