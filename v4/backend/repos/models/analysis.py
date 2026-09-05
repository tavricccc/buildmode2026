"""Analysis result."""

from __future__ import annotations

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base


class Analysis(Base):
    __tablename__ = "analyses"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    subject_id: Mapped[str] = mapped_column(String, index=True)
    analysis_type: Mapped[str] = mapped_column(String)
    window_start: Mapped[str] = mapped_column(String)
    window_end: Mapped[str] = mapped_column(String)
    input_summary_json: Mapped[str] = mapped_column(Text)
    result_json: Mapped[str] = mapped_column(Text)
    risk_level: Mapped[str] = mapped_column(String)
    model_call_id: Mapped[str | None] = mapped_column(String, ForeignKey("model_calls.id"))
    config_version: Mapped[str] = mapped_column(String)
    created_at: Mapped[str] = mapped_column(String)
