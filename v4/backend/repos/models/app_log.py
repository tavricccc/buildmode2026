"""Application log."""

from __future__ import annotations

from sqlalchemy import Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base


class AppLog(Base):
    __tablename__ = "app_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[str] = mapped_column(String, index=True)
    level: Mapped[str] = mapped_column(String)
    component: Mapped[str] = mapped_column(String)
    event_id: Mapped[str | None] = mapped_column(String)
    message: Mapped[str] = mapped_column(String)
    context_json: Mapped[str] = mapped_column(Text, default="{}")
