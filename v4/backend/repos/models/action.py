"""Action (post-policy)."""

from __future__ import annotations

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base


class Action(Base):
    __tablename__ = "actions"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    event_id: Mapped[str | None] = mapped_column(String, ForeignKey("events.id"))
    analysis_id: Mapped[str | None] = mapped_column(String, ForeignKey("analyses.id"))
    action_type: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String)
    policy_version: Mapped[str] = mapped_column(String)
    idempotency_key: Mapped[str] = mapped_column(String, unique=True)
    payload_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(String)
    completed_at: Mapped[str | None] = mapped_column(String)
