"""One durable image review per vehicle event; independent of human handling."""
from sqlalchemy import Float, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..db.base import Base


class FallReview(Base):
    __tablename__ = 'fall_reviews'

    incident_id: Mapped[str] = mapped_column(ForeignKey('incidents.id'), primary_key=True)
    state: Mapped[str] = mapped_column(String(24), default='pending', index=True)
    raw_key: Mapped[str] = mapped_column(String(512))
    model: Mapped[str] = mapped_column(String(128), default='')
    result: Mapped[str] = mapped_column(Text, default='{}')
    error: Mapped[str] = mapped_column(String(255), default='')
    started_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    finished_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    elapsed_ms: Mapped[int | None] = mapped_column(nullable=True)
