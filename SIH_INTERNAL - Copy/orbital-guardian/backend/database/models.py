import enum
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .connection import Base


def utcnow():
    return datetime.now(timezone.utc)


class Satellite(Base):
    __tablename__ = "satellites"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    norad_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)

    name: Mapped[str] = mapped_column(String(120), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    __table_args__ = (UniqueConstraint("norad_id", name="uq_satellites_norad_id"),)


class Forecast(Base):
    __tablename__ = "forecasts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    start_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    horizon_hours: Mapped[float] = mapped_column(Float, nullable=False)

    step_minutes: Mapped[int] = mapped_column(Integer, nullable=False)

    # Future auth integration (Phase 12).
    # Plain column for now; add ForeignKey("users.id")
    # when the auth team's users table exists.
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    conjunctions: Mapped[list["Conjunction"]] = relationship(back_populates="forecast")


class Conjunction(Base):
    __tablename__ = "conjunctions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    forecast_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("forecasts.id"), nullable=True
    )

    satellite_a_norad_id: Mapped[int] = mapped_column(Integer, nullable=False)

    satellite_b_norad_id: Mapped[int] = mapped_column(Integer, nullable=False)

    tca: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    minimum_distance_km: Mapped[float] = mapped_column(Float, nullable=False)

    coarse_tca: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    coarse_distance_km: Mapped[float | None] = mapped_column(Float, nullable=True)

    risk_status: Mapped[str] = mapped_column(String(20), nullable=False)

    # Operational Risk Priority score 0-100
    # (heuristic screening priority, NOT Pc).
    risk_score: Mapped[int | None] = mapped_column(Integer, nullable=True)

    relative_velocity_km_s: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Explainable factor breakdown + confidence,
    # stored as JSON so the schema stays flexible.
    risk_factors: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)

    refined: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Future auth integration (Phase 12).
    # Plain column for now; add ForeignKey("users.id")
    # when the auth team's users table exists.
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    forecast: Mapped["Forecast"] = relationship(back_populates="conjunctions")


# ==========================================
# AUTHENTICATION
# ==========================================


class UserRole(str, enum.Enum):
    VIEWER = "VIEWER"
    ANALYST = "ANALYST"
    ADMIN = "ADMIN"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    email: Mapped[str] = mapped_column(String(255), nullable=False)

    username: Mapped[str] = mapped_column(String(80), nullable=False)

    password_hash: Mapped[str] = mapped_column(String(512), nullable=False)

    role: Mapped[str] = mapped_column(
        String(20), default=UserRole.VIEWER.value, nullable=False
    )

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    last_login_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        UniqueConstraint("email", name="uq_users_email"),
        UniqueConstraint("username", name="uq_users_username"),
    )

    refresh_tokens: Mapped[list["RefreshToken"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False, index=True
    )

    token_hash: Mapped[str] = mapped_column(String(128), nullable=False)

    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    revoked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    user: Mapped["User"] = relationship(back_populates="refresh_tokens")

    __table_args__ = (Index("ix_refresh_tokens_hash", "token_hash"),)


# ==========================================
# ANALYSIS JOBS + LIVE PROGRESS
# ==========================================


class JobStatus(str, enum.Enum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class AnalysisJob(Base):
    __tablename__ = "analysis_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Public opaque reference (OG-J-xxxxxxxx).
    job_ref: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)

    user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=True, index=True
    )

    status: Mapped[str] = mapped_column(String(20), default=JobStatus.QUEUED.value)

    current_stage: Mapped[str | None] = mapped_column(String(64), nullable=True)

    progress_percentage: Mapped[float] = mapped_column(Float, default=0.0)

    object_count: Mapped[int] = mapped_column(Integer, default=0)

    pairs_total: Mapped[int] = mapped_column(Integer, default=0)

    pairs_processed: Mapped[int] = mapped_column(Integer, default=0)

    candidates_found: Mapped[int] = mapped_column(Integer, default=0)

    events_completed: Mapped[int] = mapped_column(Integer, default=0)

    request_payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    result_summary: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    events: Mapped[list["AnalysisJobEvent"]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )


class AnalysisJobEvent(Base):
    """Append-only progress history for a job."""

    __tablename__ = "analysis_job_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    job_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("analysis_jobs.id"), nullable=False, index=True
    )

    stage: Mapped[str] = mapped_column(String(64), nullable=False)

    message: Mapped[str | None] = mapped_column(Text, nullable=True)

    progress_percentage: Mapped[float] = mapped_column(Float, default=0.0)

    payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    job: Mapped["AnalysisJob"] = relationship(back_populates="events")


# ==========================================
# WATCHLISTS
# ==========================================


class Watchlist(Base):
    __tablename__ = "watchlists"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False, index=True
    )

    name: Mapped[str] = mapped_column(String(120), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    objects: Mapped[list["WatchlistObject"]] = relationship(
        back_populates="watchlist", cascade="all, delete-orphan"
    )


class WatchlistObject(Base):
    __tablename__ = "watchlist_objects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    watchlist_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("watchlists.id"), nullable=False, index=True
    )

    norad_id: Mapped[int] = mapped_column(Integer, nullable=False)

    name: Mapped[str | None] = mapped_column(String(120), nullable=True)

    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    watchlist: Mapped["Watchlist"] = relationship(back_populates="objects")

    __table_args__ = (
        UniqueConstraint("watchlist_id", "norad_id", name="uq_watchlist_object"),
    )


# ==========================================
# NOTIFICATIONS (IN-APP)
# ==========================================


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=True, index=True
    )
    # NULL user_id = system-wide broadcast.

    category: Mapped[str] = mapped_column(String(40), nullable=False)
    # analysis_completed | analysis_failed | high_priority_event |
    # provider_failure | stale_data

    title: Mapped[str] = mapped_column(String(200), nullable=False)

    body: Mapped[str | None] = mapped_column(Text, nullable=True)

    link: Mapped[str | None] = mapped_column(String(300), nullable=True)

    read: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


# ==========================================
# OBJECT INTELLIGENCE CACHE
# ==========================================
#
# Cached unified object profiles with source metadata,
# so external metadata providers are hit at most once
# per TTL window.


class ObjectProfileCache(Base):
    __tablename__ = "object_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    norad_id: Mapped[int] = mapped_column(Integer, nullable=False)

    profile: Mapped[dict] = mapped_column(JSON, nullable=False)

    sources: Mapped[list | None] = mapped_column(JSON, nullable=True)

    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    __table_args__ = (
        UniqueConstraint("norad_id", name="uq_object_profiles_norad_id"),
    )


# ==========================================
# REPORTS
# ==========================================


class Report(Base):
    __tablename__ = "reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    conjunction_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("conjunctions.id"), nullable=False, index=True
    )

    generated_by: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=True
    )

    content: Mapped[dict] = mapped_column(JSON, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
