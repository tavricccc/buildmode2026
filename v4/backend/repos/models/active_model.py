"""Active model binding (v4 new)."""

from __future__ import annotations

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base


class ActiveModel(Base):
    __tablename__ = "active_models"

    capability: Mapped[str] = mapped_column(String, primary_key=True)
    installed_model_id: Mapped[str] = mapped_column(String, ForeignKey("installed_models.id"))
    config_version: Mapped[str] = mapped_column(String)
    updated_at: Mapped[str] = mapped_column(String)
