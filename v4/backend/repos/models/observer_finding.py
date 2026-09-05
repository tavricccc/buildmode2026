"""Observer finding."""

from __future__ import annotations

from sqlalchemy import Float, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base


class ObserverFinding(Base):
    __tablename__ = "observer_findings"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    subject_id: Mapped[str] = mapped_column(String, index=True)
    window_start: Mapped[str] = mapped_column(String)
    window_end: Mapped[str] = mapped_column(String)
    finding_type: Mapped[str] = mapped_column(String)
    statement: Mapped[str] = mapped_column(String)
    evidence_json: Mapped[str] = mapped_column(Text)
    confidence: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String)
    created_at: Mapped[str] = mapped_column(String)
