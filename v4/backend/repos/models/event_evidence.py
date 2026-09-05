"""Event-to-evidence mapping."""

from __future__ import annotations

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base


class EventEvidence(Base):
    __tablename__ = "event_evidence"

    event_id: Mapped[str] = mapped_column(String, ForeignKey("events.id", ondelete="CASCADE"), primary_key=True)
    evidence_id: Mapped[str] = mapped_column(String, ForeignKey("evidence.id", ondelete="RESTRICT"), primary_key=True)
    role: Mapped[str] = mapped_column(String, primary_key=True)
