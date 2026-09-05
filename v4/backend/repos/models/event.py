"""Event record."""

from __future__ import annotations

from sqlalchemy import CheckConstraint, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base


class Event(Base):
    __tablename__ = "events"
    __table_args__ = (
        CheckConstraint("event_type IN ('fall','hydration')"),
        CheckConstraint("confidence >= 0 AND confidence <= 1"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    subject_id: Mapped[str] = mapped_column(String, index=True)
    event_type: Mapped[str] = mapped_column(String, index=True)
    status: Mapped[str] = mapped_column(String, index=True)
    occurred_at: Mapped[str] = mapped_column(String)
    ended_at: Mapped[str | None] = mapped_column(String)
    source_offset_ms: Mapped[int | None] = mapped_column(Integer)
    confidence: Mapped[float] = mapped_column(Float)
    attributes_json: Mapped[str] = mapped_column(Text, default="{}")
    model_call_id: Mapped[str | None] = mapped_column(String)
    dedup_key: Mapped[str] = mapped_column(String, unique=True)
    schema_version: Mapped[str] = mapped_column(String)
    created_at: Mapped[str] = mapped_column(String)
    updated_at: Mapped[str] = mapped_column(String)
