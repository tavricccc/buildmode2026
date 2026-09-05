"""Daily summary (Observer input)."""

from __future__ import annotations

from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base


class DailySummary(Base):
    __tablename__ = "daily_summaries"

    subject_id: Mapped[str] = mapped_column(String, primary_key=True)
    summary_date: Mapped[str] = mapped_column(String, primary_key=True)
    event_counts_json: Mapped[str] = mapped_column(Text)
    hydration_json: Mapped[str] = mapped_column(Text)
    health_json: Mapped[str] = mapped_column(Text)
    coverage_json: Mapped[str] = mapped_column(Text)
    config_version: Mapped[str] = mapped_column(String, primary_key=True)
    created_at: Mapped[str] = mapped_column(String)
