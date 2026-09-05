"""Speech transcript."""

from __future__ import annotations

from sqlalchemy import Float, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base


class Transcript(Base):
    __tablename__ = "transcripts"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    subject_id: Mapped[str] = mapped_column(String, index=True)
    event_id: Mapped[str | None] = mapped_column(String, ForeignKey("events.id"))
    started_at: Mapped[str] = mapped_column(String)
    ended_at: Mapped[str] = mapped_column(String)
    text: Mapped[str | None] = mapped_column(Text)
    language: Mapped[str | None] = mapped_column(String)
    confidence: Mapped[float | None] = mapped_column(Float)
    retention_until: Mapped[str | None] = mapped_column(String)
    model_call_id: Mapped[str | None] = mapped_column(String, ForeignKey("model_calls.id"))
    created_at: Mapped[str] = mapped_column(String)
