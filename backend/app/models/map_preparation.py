from sqlalchemy import Float, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from ..db.base import Base


class MapPreparation(Base):
    __tablename__ = 'map_preparations'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id'))
    robot_id: Mapped[str] = mapped_column(ForeignKey('robots.id'))
    active_robot: Mapped[str | None] = mapped_column(String(36), unique=True, nullable=True)
    address: Mapped[str] = mapped_column(String(512))
    session_id: Mapped[str] = mapped_column(String(128))
    lease_run_id: Mapped[str] = mapped_column(String(128))
    request: Mapped[str] = mapped_column(Text)
    state: Mapped[str] = mapped_column(String(24), default='pending', index=True)
    phase: Mapped[str] = mapped_column(String(32), default='pending')
    message: Mapped[str] = mapped_column(String(512), default='等待准备地图')
    map_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    started_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    finished_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[float] = mapped_column(Float)
