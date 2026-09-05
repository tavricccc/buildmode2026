"""Health sample (Fake Health scenarios)."""

from __future__ import annotations

from sqlalchemy import Float, String
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base


class HealthSample(Base):
    __tablename__ = "health_samples"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    subject_id: Mapped[str] = mapped_column(String, index=True)
    metric: Mapped[str] = mapped_column(String, index=True)
    value_num: Mapped[float | None] = mapped_column(Float)
    value_text: Mapped[str | None] = mapped_column(String)
    unit: Mapped[str | None] = mapped_column(String)
    measured_at: Mapped[str] = mapped_column(String)
    source: Mapped[str] = mapped_column(String, default="fake")
    quality: Mapped[str] = mapped_column(String, default="valid")
    created_at: Mapped[str] = mapped_column(String)
