"""Hydration session."""

from __future__ import annotations

from sqlalchemy import Float, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base


class HydrationSession(Base):
    __tablename__ = "hydration_sessions"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    event_id: Mapped[str] = mapped_column(String, ForeignKey("events.id"), unique=True)
    subject_id: Mapped[str] = mapped_column(String, index=True)
    started_at: Mapped[str] = mapped_column(String)
    ended_at: Mapped[str] = mapped_column(String)
    estimated_ml: Mapped[float] = mapped_column(Float)
    estimation_method: Mapped[str] = mapped_column(String)
    estimation_confidence: Mapped[float] = mapped_column(Float)
    created_at: Mapped[str] = mapped_column(String)
