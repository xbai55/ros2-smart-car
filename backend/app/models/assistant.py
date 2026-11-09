from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ..db.base import Base


def utcnow():
    return datetime.now(timezone.utc)


class AssistantSession(Base):
    __tablename__ = "assistant_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    turn_key: Mapped[str | None] = mapped_column(String(36))
    turn_until: Mapped[int] = mapped_column(Integer, default=0)


class AssistantTurn(Base):
    __tablename__ = "assistant_turns"
    __table_args__ = (UniqueConstraint("session_id", "client_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("assistant_sessions.id"), index=True)
    client_id: Mapped[str] = mapped_column(String(36))
    trace_id: Mapped[str | None] = mapped_column(String(32))
    prompt: Mapped[str] = mapped_column(Text)
    reply: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AssistantPlan(Base):
    __tablename__ = "assistant_plans"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("assistant_sessions.id"), index=True)
    robot_id: Mapped[str] = mapped_column(ForeignKey("robots.id"))
    trace_id: Mapped[str | None] = mapped_column(String(32))
    content: Mapped[str] = mapped_column(Text)
    digest: Mapped[str] = mapped_column(String(64))
    state: Mapped[str] = mapped_column(String(24), default="draft")
    version: Mapped[int] = mapped_column(Integer, default=1)
    expires_at: Mapped[int] = mapped_column(Integer)


class AssistantConfiguration(Base):
    __tablename__ = "assistant_configuration"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)


class AssistantTrialAuthorization(Base):
    __tablename__ = "assistant_trial_authorizations"

    plan_id: Mapped[str] = mapped_column(ForeignKey("assistant_plans.id"), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    plan_version: Mapped[int] = mapped_column(Integer)
    digest: Mapped[str] = mapped_column(String(64))
    fingerprint: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[int] = mapped_column(Integer)
    execution_id: Mapped[str | None] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AssistantExecution(Base):
    __tablename__ = "assistant_executions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    plan_id: Mapped[str] = mapped_column(ForeignKey("assistant_plans.id"), unique=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    robot_id: Mapped[str] = mapped_column(ForeignKey("robots.id"), index=True)
    state: Mapped[str] = mapped_column(String(24), default="queued")
    step_index: Mapped[int] = mapped_column(Integer, default=0)
    version: Mapped[int] = mapped_column(Integer, default=1)
    phase: Mapped[str] = mapped_column(String(24), default="step")
    run_id: Mapped[str | None] = mapped_column(String(36))
    run_kind: Mapped[str | None] = mapped_column(String(16))
    task_id: Mapped[str | None] = mapped_column(String(36))
    vehicle_address: Mapped[str | None] = mapped_column(String(512))
    vehicle_state: Mapped[str | None] = mapped_column(String(32))
    pending_action: Mapped[str | None] = mapped_column(String(24))
    message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AssistantEvent(Base):
    __tablename__ = "assistant_events"
    __table_args__ = {"sqlite_autoincrement": True}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    execution_id: Mapped[str | None] = mapped_column(String(36), index=True)
    kind: Mapped[str] = mapped_column(String(48))
    payload: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AssistantWorkerLock(Base):
    __tablename__ = "assistant_worker_lock"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner: Mapped[str] = mapped_column(String(36))
    expires_at: Mapped[int] = mapped_column(Integer)


class AssistantReport(Base):
    __tablename__ = "assistant_reports"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("assistant_sessions.id"), index=True)
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SafetyCoverage(Base):
    __tablename__ = "safety_coverage"

    robot_id: Mapped[str] = mapped_column(ForeignKey("robots.id"), primary_key=True)
    minute: Mapped[int] = mapped_column(Integer, primary_key=True)
    state: Mapped[str] = mapped_column(String(16))
