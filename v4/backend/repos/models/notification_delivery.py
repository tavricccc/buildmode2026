"""Notification delivery record."""

from __future__ import annotations

from sqlalchemy import CheckConstraint, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base


class NotificationDelivery(Base):
    __tablename__ = "notification_deliveries"
    __table_args__ = (CheckConstraint("channel = 'telegram'"),)

    id: Mapped[str] = mapped_column(String, primary_key=True)
    action_id: Mapped[str] = mapped_column(String, ForeignKey("actions.id"))
    channel: Mapped[str] = mapped_column(String)
    recipient_ref: Mapped[str] = mapped_column(String)
    provider_message_id: Mapped[str | None] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, index=True)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    sent_at: Mapped[str | None] = mapped_column(String)
    acknowledged_at: Mapped[str | None] = mapped_column(String)
    acknowledged_by: Mapped[str | None] = mapped_column(String)
    acknowledgement_type: Mapped[str | None] = mapped_column(String)
    last_error_code: Mapped[str | None] = mapped_column(String)
    idempotency_key: Mapped[str] = mapped_column(String, unique=True)
    created_at: Mapped[str] = mapped_column(String)
    updated_at: Mapped[str] = mapped_column(String)
